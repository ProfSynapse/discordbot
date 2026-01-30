"""
Comprehensive tests for the memory pipeline module.
Tests unit functionality, integration, and edge cases.

Test coverage targets:
- TopicDetector: time gap heuristics, Gemini response parsing, force chunk logic
- ConversationBuffer: boundary conditions, partial extracts
- ChunkPackager: output format validation, edge cases
- ConversationSummarizer: response parsing, fallback behavior
- MemoryUploader: queue persistence, retry logic
- ConversationMemoryPipeline: integration flow
"""

import pytest
import asyncio
import tempfile
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_messages():
    """Create a list of sample ConversationMessage objects."""
    from memory.models import ConversationMessage

    base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
    return [
        ConversationMessage(
            message_id='1',
            channel_id='chan1',
            user_id='user1',
            username='Alice',
            content='Hello, can you help me with Python?',
            timestamp=base_time,
            is_bot_response=False
        ),
        ConversationMessage(
            message_id='2',
            channel_id='chan1',
            user_id='bot',
            username='Bot',
            content='Of course! What do you need help with?',
            timestamp=base_time + timedelta(seconds=30),
            is_bot_response=True
        ),
        ConversationMessage(
            message_id='3',
            channel_id='chan1',
            user_id='user1',
            username='Alice',
            content='I need to understand async/await.',
            timestamp=base_time + timedelta(minutes=1),
            is_bot_response=False
        ),
        ConversationMessage(
            message_id='4',
            channel_id='chan1',
            user_id='bot',
            username='Bot',
            content='Async/await is for concurrent programming...',
            timestamp=base_time + timedelta(minutes=1, seconds=30),
            is_bot_response=True
        ),
    ]


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_genai_client():
    """Create a mock Google genai client."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """SHIFT: NO
CONFIDENCE: 0.95
TOPIC: same topic
REASON: Continuing discussion about Python async."""
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


# ---------------------------------------------------------------------------
# TopicDetector Tests
# ---------------------------------------------------------------------------

class TestTopicDetectorTimeGap:
    """Test TopicDetector time gap heuristics."""

    def test_time_gap_above_threshold_triggers_shift(self, sample_messages):
        """A time gap > threshold should trigger a topic shift."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        # Create messages with a 35-minute gap
        base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='First message',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='user1',
                username='Alice', content='After a long break',
                timestamp=base_time + timedelta(minutes=35),  # 35 min gap
                is_bot_response=False
            ),
        ]

        detector = TopicDetector(api_key='test', time_gap_threshold=1800)  # 30 min
        result = detector._check_time_gap(messages)

        assert result.is_shift is True
        assert result.confidence == 1.0
        assert 'gap' in result.reason.lower() or '2100' in result.reason  # 35 min = 2100 sec

    def test_time_gap_below_threshold_no_shift(self, sample_messages):
        """A time gap < threshold should not trigger a shift."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test', time_gap_threshold=1800)
        result = detector._check_time_gap(sample_messages)  # gaps are < 30 min

        assert result.is_shift is False
        assert result.confidence == 1.0
        assert 'no significant' in result.reason.lower()

    def test_time_gap_single_message_no_shift(self):
        """A single message cannot have a time gap."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='Only message',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
        ]

        detector = TopicDetector(api_key='test')
        result = detector._check_time_gap(messages)

        assert result.is_shift is False
        assert 'not enough messages' in result.reason.lower()

    def test_time_gap_empty_list(self):
        """An empty message list should return no shift."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        result = detector._check_time_gap([])

        assert result.is_shift is False

    def test_time_gap_timezone_naive_handling(self):
        """Timezone-naive datetimes should be handled correctly."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        # Create messages with timezone-naive timestamps
        base_time = datetime(2026, 1, 30, 14, 0, 0)  # No tzinfo
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='First',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='user1',
                username='Alice', content='Second',
                timestamp=base_time + timedelta(minutes=35),  # 35 min gap
                is_bot_response=False
            ),
        ]

        detector = TopicDetector(api_key='test', time_gap_threshold=1800)
        result = detector._check_time_gap(messages)

        assert result.is_shift is True  # Should still detect the gap


class TestTopicDetectorGeminiParsing:
    """Test TopicDetector Gemini response parsing."""

    def test_parse_shift_yes_response(self):
        """Should correctly parse a YES shift response."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        response = """SHIFT: YES
CONFIDENCE: 0.85
TOPIC: Python debugging techniques
REASON: Conversation moved from general setup to debugging."""

        result = detector._parse_gemini_response(response)

        assert result.is_shift is True
        assert result.confidence == 0.85
        assert result.topic_summary == 'Python debugging techniques'
        assert 'debugging' in result.reason.lower()

    def test_parse_shift_no_response(self):
        """Should correctly parse a NO shift response."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        response = """SHIFT: NO
CONFIDENCE: 0.95
TOPIC: same topic
REASON: User is asking follow-up questions."""

        result = detector._parse_gemini_response(response)

        assert result.is_shift is False
        assert result.confidence == 0.95
        assert result.topic_summary is None  # "same topic" becomes None

    def test_parse_malformed_response(self):
        """Should handle malformed Gemini responses gracefully."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        response = "This is not in the expected format at all."

        result = detector._parse_gemini_response(response)

        # Should default to no shift with low confidence
        assert result.is_shift is False
        assert result.confidence == 0.5  # Default

    def test_parse_partial_response(self):
        """Should handle partial Gemini responses."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        response = """SHIFT: YES
CONFIDENCE: invalid
TOPIC: New Topic"""

        result = detector._parse_gemini_response(response)

        assert result.is_shift is True
        assert result.confidence == 0.5  # Default on invalid
        assert result.topic_summary == 'New Topic'

    def test_parse_case_insensitive(self):
        """Parsing should be case insensitive for keys."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        response = """shift: yes
confidence: 0.9
topic: Some Topic
reason: Because reasons."""

        result = detector._parse_gemini_response(response)

        assert result.is_shift is True
        assert result.confidence == 0.9


class TestTopicDetectorForceChunk:
    """Test TopicDetector force chunk logic."""

    def test_force_chunk_large_buffer(self):
        """Should force chunk when buffer has 50+ messages."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        base_time = datetime.now(timezone.utc)
        messages = [
            ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Message {i}',
                timestamp=base_time + timedelta(seconds=i),
                is_bot_response=i % 2 == 1
            )
            for i in range(55)  # 55 messages
        ]

        detector = TopicDetector(api_key='test')
        should_force = detector.should_force_chunk(messages)

        assert should_force is True

    def test_no_force_chunk_small_buffer(self):
        """Should not force chunk when buffer has < 50 messages."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        base_time = datetime.now(timezone.utc)
        messages = [
            ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Message {i}',
                timestamp=base_time + timedelta(seconds=i),
                is_bot_response=False
            )
            for i in range(10)
        ]

        detector = TopicDetector(api_key='test')
        should_force = detector.should_force_chunk(messages)

        assert should_force is False

    def test_force_chunk_old_messages(self):
        """Should force chunk when oldest message is too old."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        # Create messages where oldest is 45 minutes old
        old_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='User', content='Old message',
                timestamp=old_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='user1',
                username='User', content='Recent message',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            ),
        ]

        detector = TopicDetector(api_key='test')
        should_force = detector.should_force_chunk(messages, max_time_without_chunk=1800)  # 30 min

        assert should_force is True

    def test_no_force_chunk_empty_messages(self):
        """Should not force chunk for empty message list."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test')
        should_force = detector.should_force_chunk([])

        assert should_force is False


class TestTopicDetectorDetectShift:
    """Test TopicDetector.detect_shift async method."""

    @pytest.mark.asyncio
    async def test_detect_shift_insufficient_messages(self, sample_messages):
        """Should return no shift when not enough messages."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test', min_messages_for_detection=4)
        messages = sample_messages[:2]  # Only 2 messages

        result = await detector.detect_shift(messages)

        assert result.is_shift is False
        assert 'insufficient' in result.reason.lower()

    @pytest.mark.asyncio
    async def test_detect_shift_time_gap_wins(self):
        """Time gap detection should run before Gemini and win if detected."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='User', content='Msg 1',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='bot',
                username='Bot', content='Reply 1',
                timestamp=base_time + timedelta(seconds=30), is_bot_response=True
            ),
            ConversationMessage(
                message_id='3', channel_id='chan1', user_id='user1',
                username='User', content='Msg 2',
                timestamp=base_time + timedelta(minutes=1), is_bot_response=False
            ),
            ConversationMessage(
                message_id='4', channel_id='chan1', user_id='user1',
                username='User', content='After long break',
                timestamp=base_time + timedelta(minutes=35),  # 34 min gap
                is_bot_response=False
            ),
        ]

        detector = TopicDetector(api_key='test', min_messages_for_detection=4)
        result = await detector.detect_shift(messages)

        assert result.is_shift is True
        assert 'gap' in result.reason.lower()

    @pytest.mark.asyncio
    async def test_detect_shift_gemini_api_error(self, sample_messages):
        """Should fail open (no shift) when Gemini API errors."""
        from memory.detector import TopicDetector

        detector = TopicDetector(api_key='test', min_messages_for_detection=4)

        # Mock Gemini to raise an exception
        with patch.object(detector, '_analyze_with_gemini', side_effect=Exception("API Error")):
            result = await detector.detect_shift(sample_messages)

        assert result.is_shift is False
        assert result.confidence == 0.0
        assert 'api error' in result.reason.lower()


# ---------------------------------------------------------------------------
# ConversationBuffer Extended Tests
# ---------------------------------------------------------------------------

class TestConversationBufferBoundaryConditions:
    """Test ConversationBuffer boundary conditions."""

    def test_exact_max_size(self):
        """Buffer should handle exactly max_size messages."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=5)

        for i in range(5):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
            buffer.add_message(msg)

        messages = buffer.get_messages('chan1')
        assert len(messages) == 5
        assert messages[0].message_id == '0'
        assert messages[-1].message_id == '4'

    def test_one_over_max_size(self):
        """Adding one over max should evict oldest."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=5)

        for i in range(6):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
            buffer.add_message(msg)

        messages = buffer.get_messages('chan1')
        assert len(messages) == 5
        assert messages[0].message_id == '1'  # 0 was evicted
        assert messages[-1].message_id == '5'

    def test_get_messages_with_count(self):
        """get_messages with count should return last N messages."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=10)

        for i in range(10):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
            buffer.add_message(msg)

        messages = buffer.get_messages('chan1', count=3)
        assert len(messages) == 3
        assert messages[0].message_id == '7'
        assert messages[-1].message_id == '9'

    def test_get_messages_count_larger_than_buffer(self):
        """get_messages with count > buffer size should return all."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=10)

        for i in range(5):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
            buffer.add_message(msg)

        messages = buffer.get_messages('chan1', count=10)
        assert len(messages) == 5

    def test_get_messages_nonexistent_channel(self):
        """get_messages for nonexistent channel should return empty list."""
        from memory.buffer import ConversationBuffer

        buffer = ConversationBuffer()
        messages = buffer.get_messages('nonexistent')

        assert messages == []

    def test_extract_partial_messages(self):
        """extract_and_clear with count should extract oldest N."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=10)

        for i in range(10):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            )
            buffer.add_message(msg)

        # Extract 5 oldest
        extracted = buffer.extract_and_clear('chan1', count=5)
        assert len(extracted) == 5
        assert extracted[0].message_id == '0'
        assert extracted[-1].message_id == '4'

        # 5 should remain
        remaining = buffer.get_messages('chan1')
        assert len(remaining) == 5
        assert remaining[0].message_id == '5'

    def test_get_messages_since(self):
        """get_messages_since should filter by timestamp."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer()
        base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)

        for i in range(5):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=base_time + timedelta(minutes=i * 10),
                is_bot_response=False
            )
            buffer.add_message(msg)

        # Get messages after 25 minutes (should get messages 3 and 4)
        since = base_time + timedelta(minutes=25)
        messages = buffer.get_messages_since('chan1', since)

        assert len(messages) == 2
        assert messages[0].message_id == '3'
        assert messages[1].message_id == '4'

    def test_get_time_since_last_activity(self):
        """get_time_since_last_activity should return seconds."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer()

        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content='Test',
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=30),
            is_bot_response=False
        )
        buffer.add_message(msg)

        time_since = buffer.get_time_since_last_activity('chan1')
        assert time_since is not None
        assert 29 <= time_since <= 32  # Allow for timing variance

    def test_get_time_since_last_activity_none(self):
        """get_time_since_last_activity for empty channel should return None."""
        from memory.buffer import ConversationBuffer

        buffer = ConversationBuffer()
        time_since = buffer.get_time_since_last_activity('nonexistent')

        assert time_since is None


# ---------------------------------------------------------------------------
# ChunkPackager Extended Tests
# ---------------------------------------------------------------------------

class TestChunkPackagerEdgeCases:
    """Test ChunkPackager edge cases."""

    def test_package_empty_messages_raises(self, temp_data_dir):
        """Packaging empty message list should raise ValueError."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)

        with pytest.raises(ValueError, match="empty"):
            packager.package_chunk([], 'chan1', 'test-channel', None)

    def test_package_single_message(self, temp_data_dir):
        """Packaging single message should work."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='Alice', content='Single message',
            timestamp=datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            is_bot_response=False
        )

        chunk = packager.package_chunk([msg], 'chan1', 'test-channel', None)

        assert chunk.metadata.message_count == 1
        assert chunk.metadata.timestamp_start == chunk.metadata.timestamp_end
        assert 'Alice' in chunk.metadata.participants

    def test_chunk_id_uniqueness(self, temp_data_dir):
        """Different messages should produce different chunk IDs."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        msg1 = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='Alice', content='Message 1',
            timestamp=datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            is_bot_response=False
        )
        msg2 = ConversationMessage(
            message_id='2', channel_id='chan1', user_id='user1',
            username='Alice', content='Message 2',
            timestamp=datetime(2026, 1, 30, 14, 0, 1, tzinfo=timezone.utc),
            is_bot_response=False
        )

        chunk1 = packager.package_chunk([msg1], 'chan1', 'test', None)
        chunk2 = packager.package_chunk([msg2], 'chan1', 'test', None)

        assert chunk1.metadata.chunk_id != chunk2.metadata.chunk_id

    def test_chunk_id_length(self, temp_data_dir, sample_messages):
        """Chunk ID should be 12 characters."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)

        assert len(chunk.metadata.chunk_id) == 12

    def test_to_dict_without_reflection(self, temp_data_dir, sample_messages):
        """to_dict should work without reflection."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)

        data = chunk.to_dict()

        assert 'messages' in data
        assert 'metadata' in data
        assert 'reflection' not in data  # Should not be present when None

    def test_to_dict_with_reflection(self, temp_data_dir, sample_messages):
        """to_dict should include reflection when present."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)

        reflection = Reflection(
            topic='Python Async',
            what_happened='Discussion about async/await.',
            key_insights=['Important insight'],
            tags=['python', 'async']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        data = chunk.to_dict()

        assert 'reflection' in data
        assert data['reflection']['topic'] == 'Python Async'
        assert 'Important insight' in data['reflection']['key_insights']

    def test_markdown_without_reflection(self, temp_data_dir, sample_messages):
        """Markdown output should work without reflection."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test-channel', None)

        md = packager.to_markdown(chunk)

        assert 'type: conversation' in md
        assert 'channel: test-channel' in md
        assert '## Transcript' in md
        assert 'Alice: Hello' in md
        # Should not have reflection section
        assert '## Reflection' not in md

    def test_markdown_frontmatter_structure(self, temp_data_dir, sample_messages):
        """Markdown frontmatter should have correct YAML structure."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test Topic',
            what_happened='Test description.',
            tags=['tag1', 'tag2']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test-channel', reflection)
        md = packager.to_markdown(chunk)

        # Check frontmatter delimiters
        lines = md.split('\n')
        assert lines[0] == '---'

        # Find second delimiter
        end_index = None
        for i, line in enumerate(lines[1:], 1):
            if line == '---':
                end_index = i
                break

        assert end_index is not None

        # Check required fields
        frontmatter = '\n'.join(lines[1:end_index])
        assert 'type: conversation' in frontmatter
        assert 'topic: Test Topic' in frontmatter
        assert 'channel: test-channel' in frontmatter
        assert 'date:' in frontmatter
        assert 'message_count:' in frontmatter

    def test_save_jsonl_creates_directory(self, temp_data_dir, sample_messages):
        """save_jsonl should create channel directory if needed."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunk = packager.package_chunk(sample_messages, 'new_channel', 'test', None)

        path = packager.save_jsonl(chunk)

        assert Path(path).exists()
        assert 'new_channel' in path

    def test_save_jsonl_appends(self, temp_data_dir, sample_messages):
        """Multiple save_jsonl calls should append to same file."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)

        chunk1 = packager.package_chunk(sample_messages[:2], 'chan1', 'test', None)
        chunk2 = packager.package_chunk(sample_messages[2:], 'chan1', 'test', None)

        path1 = packager.save_jsonl(chunk1)
        path2 = packager.save_jsonl(chunk2)

        assert path1 == path2

        # Verify both lines are in the file
        with open(path1, 'r') as f:
            lines = f.readlines()

        assert len(lines) == 2

    def test_get_daily_chunks_nonexistent_file(self, temp_data_dir):
        """get_daily_chunks for nonexistent file should return empty list."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunks = packager.get_daily_chunks('nonexistent', datetime.now())

        assert chunks == []


# ---------------------------------------------------------------------------
# ConversationSummarizer Tests
# ---------------------------------------------------------------------------

class TestConversationSummarizerParsing:
    """Test ConversationSummarizer response parsing."""

    def test_parse_valid_json_response(self):
        """Should parse valid JSON response correctly."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        response = '''{
            "topic": "Python Async Programming",
            "what_happened": "User asked about async/await patterns.",
            "key_insights": ["Async improves I/O performance", "await suspends execution"],
            "about_the_user": ["Interested in Python"],
            "decisions_made": [],
            "what_went_well": ["Clear explanations"],
            "what_could_improve": [],
            "connections": {
                "related_topics": ["concurrency", "threading"],
                "likely_next_questions": ["How to handle exceptions in async?"]
            },
            "tags": ["python", "async", "programming"]
        }'''

        reflection = summarizer._parse_reflection_response(response)

        assert reflection.topic == 'Python Async Programming'
        assert 'async/await' in reflection.what_happened
        assert len(reflection.key_insights) == 2
        assert 'python' in reflection.tags

    def test_parse_markdown_wrapped_json(self):
        """Should parse JSON wrapped in markdown code blocks."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        response = '''```json
{
    "topic": "Test Topic",
    "what_happened": "Something happened.",
    "key_insights": [],
    "about_the_user": [],
    "decisions_made": [],
    "what_went_well": [],
    "what_could_improve": [],
    "connections": {"related_topics": [], "likely_next_questions": []},
    "tags": []
}
```'''

        reflection = summarizer._parse_reflection_response(response)

        assert reflection.topic == 'Test Topic'

    def test_parse_invalid_json(self):
        """Should return empty reflection for invalid JSON."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        response = "This is not valid JSON at all."

        reflection = summarizer._parse_reflection_response(response)

        assert reflection.topic == 'Empty Conversation'

    def test_parse_partial_json(self):
        """Should handle partial JSON with missing fields."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        response = '''{
            "topic": "Partial Topic",
            "what_happened": "Something happened."
        }'''

        reflection = summarizer._parse_reflection_response(response)

        assert reflection.topic == 'Partial Topic'
        assert reflection.key_insights == []  # Default

    def test_empty_reflection(self):
        """_empty_reflection should return valid defaults."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)
        reflection = summarizer._empty_reflection()

        assert reflection.topic == 'Empty Conversation'
        assert reflection.what_happened == 'No messages to analyze.'
        assert reflection.key_insights == []
        assert reflection.connections['related_topics'] == []

    def test_fallback_reflection(self):
        """_fallback_reflection should use message content."""
        from memory.summarizer import ConversationSummarizer
        from memory.models import ConversationMessage

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='How do I configure the database?',
                timestamp=datetime.now(timezone.utc), is_bot_response=False
            ),
        ]

        reflection = summarizer._fallback_reflection(messages, ['Alice'])

        assert 'How do I configure' in reflection.topic
        assert 'Alice' in reflection.what_happened

    @pytest.mark.asyncio
    async def test_generate_reflection_empty_messages(self):
        """generate_reflection with empty messages returns empty reflection."""
        from memory.summarizer import ConversationSummarizer

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)
        summarizer.client = MagicMock()

        reflection = await summarizer.generate_reflection([], 'test-channel')

        assert reflection.topic == 'Empty Conversation'


# ---------------------------------------------------------------------------
# MemoryUploader Tests
# ---------------------------------------------------------------------------

class TestMemoryUploaderQueue:
    """Test MemoryUploader queue operations."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, temp_data_dir):
        """initialize should create the database schema."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        # Verify database exists and has correct schema
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            # Check table exists
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_chunks'"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None

    @pytest.mark.asyncio
    async def test_queue_chunk(self, temp_data_dir, sample_messages):
        """queue_chunk should add chunk to database."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        reflection = Reflection(topic='Test', what_happened='Test description.')
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)

        result = await uploader.queue_chunk(chunk)

        assert result is True

        # Verify in database
        stats = await uploader.get_upload_stats()
        assert stats['pending'] == 1

    @pytest.mark.asyncio
    async def test_queue_chunk_duplicate(self, temp_data_dir, sample_messages):
        """queue_chunk should reject duplicate chunks."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)

        result1 = await uploader.queue_chunk(chunk)
        result2 = await uploader.queue_chunk(chunk)

        assert result1 is True
        assert result2 is False  # Duplicate

        stats = await uploader.get_upload_stats()
        assert stats['pending'] == 1  # Still only 1

    @pytest.mark.asyncio
    async def test_is_chunk_processed(self, temp_data_dir, sample_messages):
        """is_chunk_processed should check database."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)
        chunk_hash = chunk.metadata.chunk_id

        # Not processed yet
        assert await uploader.is_chunk_processed(chunk_hash) is False

        # Queue it
        await uploader.queue_chunk(chunk)

        # Now processed
        assert await uploader.is_chunk_processed(chunk_hash) is True

    @pytest.mark.asyncio
    async def test_get_pending_chunks(self, temp_data_dir, sample_messages):
        """_get_pending_chunks should return pending items."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        # Create 3 different chunks
        for i in range(3):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime(2026, 1, 30, 14, i, 0, tzinfo=timezone.utc),
                is_bot_response=False
            )
            chunk = packager.package_chunk([msg], 'chan1', 'test', None)
            await uploader.queue_chunk(chunk)

        pending = await uploader._get_pending_chunks(limit=2)

        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_mark_uploaded(self, temp_data_dir, sample_messages):
        """_mark_uploaded should update status."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)
        await uploader.queue_chunk(chunk)

        # Get the chunk ID
        pending = await uploader._get_pending_chunks(limit=1)
        chunk_id = pending[0]['id']

        await uploader._mark_uploaded(chunk_id)

        stats = await uploader.get_upload_stats()
        assert stats['pending'] == 0
        assert stats['uploaded'] == 1

    @pytest.mark.asyncio
    async def test_mark_retry_increments_count(self, temp_data_dir, sample_messages):
        """_mark_retry should increment retry count."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager
        import aiosqlite

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)
        await uploader.queue_chunk(chunk)

        pending = await uploader._get_pending_chunks(limit=1)
        chunk_id = pending[0]['id']

        await uploader._mark_retry(chunk_id, "Test error")

        # Check retry count
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT retry_count, error_message FROM conversation_chunks WHERE id = ?",
                (chunk_id,)
            ) as cursor:
                row = await cursor.fetchone()
                assert row[0] == 1
                assert row[1] == "Test error"

    @pytest.mark.asyncio
    async def test_mark_retry_max_retries_fails(self, temp_data_dir, sample_messages):
        """After 5 retries, status should become 'failed'."""
        from memory.uploader import MemoryUploader
        from memory.packager import ChunkPackager

        db_path = os.path.join(temp_data_dir, 'test.db')
        packager = ChunkPackager(data_dir=temp_data_dir)
        uploader = MemoryUploader(
            api_client=MagicMock(),
            packager=packager,
            db_path=db_path
        )

        await uploader.initialize()

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)
        await uploader.queue_chunk(chunk)

        pending = await uploader._get_pending_chunks(limit=1)
        chunk_id = pending[0]['id']

        # Retry 5 times
        for i in range(5):
            await uploader._mark_retry(chunk_id, f"Error {i}")

        stats = await uploader.get_upload_stats()
        assert stats['pending'] == 0
        assert stats['failed'] == 1


# ---------------------------------------------------------------------------
# ConversationMemoryPipeline Integration Tests
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Integration tests for ConversationMemoryPipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_initialization(self, temp_data_dir):
        """Pipeline should initialize all components."""
        from memory.pipeline import ConversationMemoryPipeline

        db_path = os.path.join(temp_data_dir, 'test.db')

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1'},
            data_dir=temp_data_dir,
            db_path=db_path
        )

        await pipeline.initialize()

        assert pipeline.buffer is not None
        assert pipeline.detector is not None
        assert pipeline.summarizer is not None
        assert pipeline.packager is not None
        assert pipeline.uploader is not None

    def test_track_message_enabled_channel(self, temp_data_dir):
        """track_message should add message to buffer for enabled channel."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'123456789'},
            data_dir=temp_data_dir
        )

        # Create mock Discord message
        mock_message = MagicMock()
        mock_message.channel.id = 123456789
        mock_message.id = 1
        mock_message.author.id = 1001
        mock_message.author.display_name = 'TestUser'
        mock_message.author.bot = False
        mock_message.content = 'Hello!'
        mock_message.created_at = datetime.now(timezone.utc)

        pipeline.track_message(mock_message)

        assert pipeline.buffer.size('123456789') == 1

    def test_track_message_disabled_channel(self, temp_data_dir):
        """track_message should ignore messages from disabled channels."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1'},  # Different channel
            data_dir=temp_data_dir
        )

        mock_message = MagicMock()
        mock_message.channel.id = 999999  # Not enabled
        mock_message.id = 1
        mock_message.author.id = 1001
        mock_message.author.display_name = 'TestUser'
        mock_message.author.bot = False
        mock_message.content = 'Hello!'
        mock_message.created_at = datetime.now(timezone.utc)

        pipeline.track_message(mock_message)

        assert pipeline.buffer.total_messages() == 0

    def test_track_message_empty_content(self, temp_data_dir):
        """track_message should ignore empty messages."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'123456789'},
            data_dir=temp_data_dir
        )

        mock_message = MagicMock()
        mock_message.channel.id = 123456789
        mock_message.id = 1
        mock_message.author.id = 1001
        mock_message.author.display_name = 'TestUser'
        mock_message.author.bot = False
        mock_message.content = '   '  # Whitespace only
        mock_message.created_at = datetime.now(timezone.utc)

        pipeline.track_message(mock_message)

        assert pipeline.buffer.total_messages() == 0

    def test_get_stats(self, temp_data_dir):
        """get_stats should return pipeline statistics."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1', 'chan2'},
            data_dir=temp_data_dir
        )

        stats = pipeline.get_stats()

        assert stats['enabled_channels'] == 2
        assert stats['active_channels'] == 0
        assert stats['total_buffered_messages'] == 0
        assert stats['running'] is False

    @pytest.mark.asyncio
    async def test_force_chunk_all(self, temp_data_dir):
        """force_chunk_all should chunk all active channels."""
        from memory.pipeline import ConversationMemoryPipeline
        from memory.models import ConversationMessage, Reflection

        db_path = os.path.join(temp_data_dir, 'test.db')

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1'},
            data_dir=temp_data_dir,
            db_path=db_path
        )

        await pipeline.initialize()

        # Add messages to buffer
        for i in range(5):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=False
            )
            pipeline.buffer.add_message(msg)

        # Mock summarizer to avoid API call
        mock_reflection = Reflection(topic='Test', what_happened='Test.')
        pipeline.summarizer.generate_reflection = AsyncMock(return_value=mock_reflection)

        chunks_created = await pipeline.force_chunk_all()

        assert chunks_created == 1
        assert pipeline.buffer.size('chan1') == 0

    @pytest.mark.asyncio
    async def test_channel_name_resolver(self, temp_data_dir):
        """Channel name resolver should be called."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1'},
            data_dir=temp_data_dir
        )

        # Set resolver
        async def resolver(channel_id):
            return f"resolved-{channel_id}"

        pipeline.set_channel_name_resolver(resolver)

        name = await pipeline._get_channel_name('chan1')

        assert name == 'resolved-chan1'

    @pytest.mark.asyncio
    async def test_channel_name_resolver_error_fallback(self, temp_data_dir):
        """Should fallback to ID if resolver fails."""
        from memory.pipeline import ConversationMemoryPipeline

        pipeline = ConversationMemoryPipeline(
            api_key='test',
            api_client=MagicMock(),
            enabled_channels={'chan1'},
            data_dir=temp_data_dir
        )

        async def failing_resolver(channel_id):
            raise Exception("Lookup failed")

        pipeline.set_channel_name_resolver(failing_resolver)

        name = await pipeline._get_channel_name('chan1')

        assert name == 'channel-chan1'


# ---------------------------------------------------------------------------
# ConversationChunk Model Tests
# ---------------------------------------------------------------------------

class TestConversationChunkModel:
    """Test ConversationChunk model methods."""

    def test_to_chatml_messages(self, sample_messages):
        """to_chatml_messages should produce correct roles."""
        from memory.models import ConversationChunk, ChunkMetadata

        metadata = ChunkMetadata(
            chunk_id='test123',
            channel_id='chan1',
            channel_name='test',
            timestamp_start=sample_messages[0].timestamp,
            timestamp_end=sample_messages[-1].timestamp,
            participants=['Alice'],
            message_count=4
        )

        chunk = ConversationChunk(messages=sample_messages, metadata=metadata)
        chatml = chunk.to_chatml_messages()

        assert len(chatml) == 4
        assert chatml[0] == {'role': 'user', 'content': 'Hello, can you help me with Python?'}
        assert chatml[1] == {'role': 'assistant', 'content': 'Of course! What do you need help with?'}
        assert chatml[2]['role'] == 'user'
        assert chatml[3]['role'] == 'assistant'

    def test_to_dict_metadata_fields(self, sample_messages):
        """to_dict should include all metadata fields."""
        from memory.models import ConversationChunk, ChunkMetadata

        metadata = ChunkMetadata(
            chunk_id='test123',
            channel_id='chan1',
            channel_name='test-channel',
            timestamp_start=sample_messages[0].timestamp,
            timestamp_end=sample_messages[-1].timestamp,
            participants=['Alice'],
            message_count=4,
            topic='Python Help'
        )

        chunk = ConversationChunk(messages=sample_messages, metadata=metadata)
        data = chunk.to_dict()

        assert data['metadata']['chunk_id'] == 'test123'
        assert data['metadata']['channel_id'] == 'chan1'
        assert data['metadata']['channel_name'] == 'test-channel'
        assert data['metadata']['participants'] == ['Alice']
        assert data['metadata']['message_count'] == 4


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_buffer_100_messages(self):
        """Buffer should handle exactly 100 messages (default max)."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer()  # Default max_size=100

        for i in range(100):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=False
            )
            buffer.add_message(msg)

        assert buffer.size('chan1') == 100

        # Add one more
        msg = ConversationMessage(
            message_id='100', channel_id='chan1', user_id='user1',
            username='User', content='Overflow msg',
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )
        buffer.add_message(msg)

        assert buffer.size('chan1') == 100
        messages = buffer.get_messages('chan1')
        assert messages[0].message_id == '1'  # First was evicted
        assert messages[-1].message_id == '100'

    def test_packager_bot_only_conversation(self, temp_data_dir):
        """Participants should be empty if only bot messages."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='bot',
                username='Bot', content='Hello!',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=True
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='bot',
                username='Bot', content='Anyone there?',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=True
            ),
        ]

        chunk = packager.package_chunk(messages, 'chan1', 'test', None)

        assert chunk.metadata.participants == []

    def test_very_long_message_content(self, temp_data_dir):
        """Should handle very long message content."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        long_content = 'A' * 10000  # 10KB message
        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content=long_content,
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )

        chunk = packager.package_chunk([msg], 'chan1', 'test', None)

        assert len(chunk.messages[0].content) == 10000

    def test_unicode_content(self, temp_data_dir):
        """Should handle unicode characters correctly."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        unicode_content = 'Hello! 🎉 こんにちは 你好 مرحبا'
        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content=unicode_content,
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )

        chunk = packager.package_chunk([msg], 'chan1', 'test', None)
        path = packager.save_jsonl(chunk)

        # Verify can read back
        with open(path, 'r', encoding='utf-8') as f:
            data = json.loads(f.readline())

        assert '🎉' in data['messages'][0]['content']
        assert 'こんにちは' in data['messages'][0]['content']

    def test_special_characters_in_channel_name(self, temp_data_dir):
        """Should handle special characters in channel names."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage, Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)

        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content='Test',
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )

        reflection = Reflection(
            topic='Test Topic',
            what_happened='Test.',
            tags=['special:tag', 'another-tag']
        )

        chunk = packager.package_chunk([msg], 'chan1', 'test-channel_special', reflection)
        md = packager.to_markdown(chunk)

        assert 'channel: test-channel_special' in md


# ---------------------------------------------------------------------------
# Additional Coverage Tests for Packager Markdown
# ---------------------------------------------------------------------------

class TestPackagerMarkdownSections:
    """Test markdown generation for various reflection sections."""

    def test_markdown_with_about_the_user(self, temp_data_dir, sample_messages):
        """Markdown should include 'About the User' section."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test',
            what_happened='Test description.',
            about_the_user=['User prefers detailed explanations', 'User is a beginner']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        md = packager.to_markdown(chunk)

        assert '### What I Learned About the User' in md
        assert 'User prefers detailed explanations' in md
        assert 'User is a beginner' in md

    def test_markdown_with_decisions(self, temp_data_dir, sample_messages):
        """Markdown should include 'Decisions Made' section."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test',
            what_happened='Test description.',
            decisions_made=['Use async/await pattern', 'Refactor the module']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        md = packager.to_markdown(chunk)

        assert '### Decisions Made' in md
        assert 'Use async/await pattern' in md

    def test_markdown_with_what_went_well(self, temp_data_dir, sample_messages):
        """Markdown should include 'What Went Well' section."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test',
            what_happened='Test description.',
            what_went_well=['Clear communication', 'User understood quickly']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        md = packager.to_markdown(chunk)

        assert '### What Went Well' in md
        assert 'Clear communication' in md

    def test_markdown_with_what_could_improve(self, temp_data_dir, sample_messages):
        """Markdown should include 'What Could Improve' section."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test',
            what_happened='Test description.',
            what_could_improve=['Provide more examples', 'Be more concise']
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        md = packager.to_markdown(chunk)

        assert '### What Could Be Improved' in md
        assert 'Provide more examples' in md

    def test_markdown_with_connections(self, temp_data_dir, sample_messages):
        """Markdown should include connections section."""
        from memory.packager import ChunkPackager
        from memory.models import Reflection

        packager = ChunkPackager(data_dir=temp_data_dir)
        reflection = Reflection(
            topic='Test',
            what_happened='Test description.',
            connections={
                'related_topics': ['python', 'concurrency'],
                'likely_next_questions': ['How to debug async?']
            }
        )

        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', reflection)
        md = packager.to_markdown(chunk)

        assert '### Connections' in md
        assert 'Related to: python, concurrency' in md
        assert 'User might next ask about: How to debug async?' in md
        # Check related section in frontmatter
        assert '[[Python]]' in md or '[[Concurrency]]' in md

    def test_markdown_participants_in_frontmatter(self, temp_data_dir, sample_messages):
        """Markdown frontmatter should list participants."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test-channel', None)
        md = packager.to_markdown(chunk)

        assert 'participants:' in md
        assert '  - Alice' in md

    def test_markdown_duration_calculation(self, temp_data_dir):
        """Markdown should calculate duration correctly."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='Start',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='user1',
                username='Alice', content='End',
                timestamp=base_time + timedelta(minutes=15),  # 15 min later
                is_bot_response=False
            ),
        ]

        chunk = packager.package_chunk(messages, 'chan1', 'test', None)
        md = packager.to_markdown(chunk)

        assert 'duration_minutes: 15' in md


class TestPackagerGetDailyChunks:
    """Test packager's get_daily_chunks method."""

    def test_get_daily_chunks_valid_file(self, temp_data_dir, sample_messages):
        """get_daily_chunks should load chunks from valid file."""
        from memory.packager import ChunkPackager

        packager = ChunkPackager(data_dir=temp_data_dir)

        # Save a chunk
        chunk = packager.package_chunk(sample_messages, 'chan1', 'test', None)
        packager.save_jsonl(chunk)

        # Load it back
        chunks = packager.get_daily_chunks('chan1', sample_messages[-1].timestamp)

        assert len(chunks) == 1
        assert chunks[0]['metadata']['channel_id'] == 'chan1'

    def test_get_daily_chunks_multiple_chunks(self, temp_data_dir):
        """get_daily_chunks should load multiple chunks from same day."""
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        packager = ChunkPackager(data_dir=temp_data_dir)

        base_time = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)

        # Save 3 chunks
        for i in range(3):
            msg = ConversationMessage(
                message_id=str(i), channel_id='chan1', user_id='user1',
                username='User', content=f'Msg {i}',
                timestamp=base_time + timedelta(hours=i),
                is_bot_response=False
            )
            chunk = packager.package_chunk([msg], 'chan1', 'test', None)
            packager.save_jsonl(chunk)

        chunks = packager.get_daily_chunks('chan1', base_time)

        assert len(chunks) == 3


# ---------------------------------------------------------------------------
# Additional Summarizer Tests
# ---------------------------------------------------------------------------

class TestSummarizerFormatConversation:
    """Test ConversationSummarizer conversation formatting."""

    def test_format_conversation(self):
        """_format_conversation should produce readable format."""
        from memory.summarizer import ConversationSummarizer
        from memory.models import ConversationMessage

        summarizer = ConversationSummarizer.__new__(ConversationSummarizer)

        base_time = datetime(2026, 1, 30, 14, 30, 45, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='Hello!',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='bot',
                username='Bot', content='Hi there!',
                timestamp=base_time + timedelta(seconds=30),
                is_bot_response=True
            ),
        ]

        formatted = summarizer._format_conversation(messages)

        assert '[14:30:45] [Alice]: Hello!' in formatted
        assert '[14:31:15] [Bot]: Hi there!' in formatted


# ---------------------------------------------------------------------------
# Additional Buffer Tests
# ---------------------------------------------------------------------------

class TestBufferClearChannel:
    """Test ConversationBuffer clear_channel method."""

    def test_clear_channel_existing(self):
        """clear_channel should clear existing channel."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer()

        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content='Test',
            timestamp=datetime.now(timezone.utc), is_bot_response=False
        )
        buffer.add_message(msg)

        assert buffer.size('chan1') == 1

        buffer.clear_channel('chan1')

        assert buffer.size('chan1') == 0

    def test_clear_channel_nonexistent(self):
        """clear_channel for nonexistent channel should not raise."""
        from memory.buffer import ConversationBuffer

        buffer = ConversationBuffer()
        buffer.clear_channel('nonexistent')  # Should not raise

    def test_get_last_activity_existing(self):
        """get_last_activity should return timestamp."""
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer()
        timestamp = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)

        msg = ConversationMessage(
            message_id='1', channel_id='chan1', user_id='user1',
            username='User', content='Test',
            timestamp=timestamp, is_bot_response=False
        )
        buffer.add_message(msg)

        last_activity = buffer.get_last_activity('chan1')

        assert last_activity == timestamp


# ---------------------------------------------------------------------------
# Detector Format Conversation Test
# ---------------------------------------------------------------------------

class TestDetectorFormatConversation:
    """Test TopicDetector conversation formatting."""

    def test_format_conversation(self):
        """_format_conversation should include role and timestamp."""
        from memory.detector import TopicDetector
        from memory.models import ConversationMessage

        detector = TopicDetector(api_key='test')

        base_time = datetime(2026, 1, 30, 14, 30, 0, tzinfo=timezone.utc)
        messages = [
            ConversationMessage(
                message_id='1', channel_id='chan1', user_id='user1',
                username='Alice', content='Question?',
                timestamp=base_time, is_bot_response=False
            ),
            ConversationMessage(
                message_id='2', channel_id='chan1', user_id='bot',
                username='Bot', content='Answer!',
                timestamp=base_time + timedelta(seconds=30),
                is_bot_response=True
            ),
        ]

        formatted = detector._format_conversation(messages)

        assert '14:30 [Alice]: Question?' in formatted
        assert '14:30 [BOT]: Answer!' in formatted


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
