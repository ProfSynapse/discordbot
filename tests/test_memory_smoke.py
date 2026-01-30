"""
Smoke tests for the memory pipeline module.
Verifies basic functionality without external API calls.
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import json


class TestConversationMessage:
    """Test ConversationMessage dataclass."""

    def test_create_message(self):
        from memory.models import ConversationMessage

        msg = ConversationMessage(
            message_id='123456',
            channel_id='789',
            user_id='user_1',
            username='TestUser',
            content='Hello world!',
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )

        assert msg.message_id == '123456'
        assert msg.channel_id == '789'
        assert msg.username == 'TestUser'
        assert msg.is_bot_response is False

    def test_bot_message(self):
        from memory.models import ConversationMessage

        msg = ConversationMessage(
            message_id='123',
            channel_id='456',
            user_id='bot_id',
            username='Bot',
            content='Hello!',
            timestamp=datetime.now(timezone.utc),
            is_bot_response=True
        )

        assert msg.is_bot_response is True


class TestConversationBuffer:
    """Test ConversationBuffer functionality."""

    def test_add_and_retrieve_messages(self):
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=100)

        msg = ConversationMessage(
            message_id='1',
            channel_id='chan1',
            user_id='user1',
            username='User',
            content='Test message',
            timestamp=datetime.now(timezone.utc),
            is_bot_response=False
        )

        buffer.add_message(msg)

        messages = buffer.get_messages('chan1')
        assert len(messages) == 1
        assert messages[0].message_id == '1'

    def test_buffer_max_size(self):
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=5)

        # Add 10 messages
        for i in range(10):
            msg = ConversationMessage(
                message_id=str(i),
                channel_id='chan1',
                user_id='user1',
                username='User',
                content=f'Message {i}',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=False
            )
            buffer.add_message(msg)

        # Should only keep last 5
        messages = buffer.get_messages('chan1')
        assert len(messages) == 5
        assert messages[0].message_id == '5'  # Oldest kept
        assert messages[-1].message_id == '9'  # Newest

    def test_extract_and_clear(self):
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=100)

        for i in range(5):
            msg = ConversationMessage(
                message_id=str(i),
                channel_id='chan1',
                user_id='user1',
                username='User',
                content=f'Message {i}',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=False
            )
            buffer.add_message(msg)

        # Extract all
        extracted = buffer.extract_and_clear('chan1')
        assert len(extracted) == 5

        # Buffer should be empty
        assert buffer.size('chan1') == 0

    def test_multiple_channels(self):
        from memory.buffer import ConversationBuffer
        from memory.models import ConversationMessage

        buffer = ConversationBuffer(max_size=100)

        for channel_id in ['chan1', 'chan2', 'chan3']:
            msg = ConversationMessage(
                message_id=f'{channel_id}_msg',
                channel_id=channel_id,
                user_id='user1',
                username='User',
                content='Test',
                timestamp=datetime.now(timezone.utc),
                is_bot_response=False
            )
            buffer.add_message(msg)

        assert buffer.size('chan1') == 1
        assert buffer.size('chan2') == 1
        assert buffer.size('chan3') == 1
        assert buffer.total_messages() == 3


class TestChunkPackager:
    """Test ChunkPackager functionality."""

    def test_package_chunk(self):
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        with tempfile.TemporaryDirectory() as tmpdir:
            packager = ChunkPackager(data_dir=tmpdir)

            msgs = [
                ConversationMessage(
                    message_id='1',
                    channel_id='456',
                    user_id='user1',
                    username='Alice',
                    content='Hello',
                    timestamp=datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
                    is_bot_response=False
                ),
                ConversationMessage(
                    message_id='2',
                    channel_id='456',
                    user_id='bot',
                    username='Bot',
                    content='Hi there!',
                    timestamp=datetime(2026, 1, 30, 14, 0, 30, tzinfo=timezone.utc),
                    is_bot_response=True
                )
            ]

            chunk = packager.package_chunk(
                messages=msgs,
                channel_id='456',
                channel_name='test-channel',
                reflection=None
            )

            assert chunk.metadata.channel_id == '456'
            assert chunk.metadata.channel_name == 'test-channel'
            assert chunk.metadata.message_count == 2
            assert 'Alice' in chunk.metadata.participants
            assert len(chunk.metadata.chunk_id) == 12  # Hash length

    def test_to_chatml_messages(self):
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        with tempfile.TemporaryDirectory() as tmpdir:
            packager = ChunkPackager(data_dir=tmpdir)

            msgs = [
                ConversationMessage(
                    message_id='1', channel_id='456', user_id='u1',
                    username='Alice', content='Question?',
                    timestamp=datetime.now(timezone.utc),
                    is_bot_response=False
                ),
                ConversationMessage(
                    message_id='2', channel_id='456', user_id='bot',
                    username='Bot', content='Answer!',
                    timestamp=datetime.now(timezone.utc),
                    is_bot_response=True
                )
            ]

            chunk = packager.package_chunk(msgs, '456', 'test', None)
            chatml = chunk.to_chatml_messages()

            assert len(chatml) == 2
            assert chatml[0] == {'role': 'user', 'content': 'Question?'}
            assert chatml[1] == {'role': 'assistant', 'content': 'Answer!'}

    def test_save_jsonl(self):
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage

        with tempfile.TemporaryDirectory() as tmpdir:
            packager = ChunkPackager(data_dir=tmpdir)

            msgs = [
                ConversationMessage(
                    message_id='1', channel_id='456', user_id='u1',
                    username='Alice', content='Test',
                    timestamp=datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
                    is_bot_response=False
                )
            ]

            chunk = packager.package_chunk(msgs, '456', 'test', None)
            path = packager.save_jsonl(chunk)

            # Verify file was created
            assert Path(path).exists()

            # Verify content is valid JSONL
            with open(path, 'r') as f:
                line = f.readline()
                data = json.loads(line)
                assert 'messages' in data
                assert 'metadata' in data

    def test_to_markdown_with_reflection(self):
        from memory.packager import ChunkPackager
        from memory.models import ConversationMessage, Reflection

        with tempfile.TemporaryDirectory() as tmpdir:
            packager = ChunkPackager(data_dir=tmpdir)

            msgs = [
                ConversationMessage(
                    message_id='1', channel_id='456', user_id='u1',
                    username='Alice', content='How do I start?',
                    timestamp=datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
                    is_bot_response=False
                ),
                ConversationMessage(
                    message_id='2', channel_id='456', user_id='bot',
                    username='Bot', content='Run python main.py',
                    timestamp=datetime(2026, 1, 30, 14, 0, 30, tzinfo=timezone.utc),
                    is_bot_response=True
                )
            ]

            reflection = Reflection(
                topic='Getting Started',
                what_happened='User asked about starting the project.',
                key_insights=['Users need clear onboarding'],
                tags=['onboarding', 'setup']
            )

            chunk = packager.package_chunk(msgs, '456', 'test-channel', reflection)
            md = packager.to_markdown(chunk)

            # Check frontmatter
            assert 'type: conversation' in md
            assert 'topic: Getting Started' in md
            assert 'channel: test-channel' in md

            # Check reflection sections
            assert '## Reflection' in md
            assert '### What Happened' in md
            assert '### Key Insights' in md

            # Check transcript
            assert '## Transcript' in md
            assert 'Alice: How do I start?' in md
            assert 'Bot: Run python main.py' in md


class TestTopicShiftResult:
    """Test TopicShiftResult dataclass."""

    def test_no_shift(self):
        from memory.models import TopicShiftResult

        result = TopicShiftResult(
            is_shift=False,
            confidence=0.95,
            reason='Same topic'
        )

        assert result.is_shift is False
        assert result.confidence == 0.95
        assert result.topic_summary is None

    def test_shift_detected(self):
        from memory.models import TopicShiftResult

        result = TopicShiftResult(
            is_shift=True,
            confidence=0.85,
            topic_summary='New Topic Discussion',
            reason='Subject matter changed'
        )

        assert result.is_shift is True
        assert result.topic_summary == 'New Topic Discussion'


class TestReflection:
    """Test Reflection dataclass."""

    def test_reflection_defaults(self):
        from memory.models import Reflection

        reflection = Reflection(
            topic='Test Topic',
            what_happened='Something happened.'
        )

        assert reflection.topic == 'Test Topic'
        assert reflection.key_insights == []
        assert reflection.about_the_user == []
        assert reflection.connections == {
            'related_topics': [],
            'likely_next_questions': []
        }

    def test_reflection_full(self):
        from memory.models import Reflection

        reflection = Reflection(
            topic='Full Test',
            what_happened='Detailed description.',
            key_insights=['Insight 1', 'Insight 2'],
            about_the_user=['User preference noted'],
            decisions_made=['Decision 1'],
            what_went_well=['Clear communication'],
            what_could_improve=['More examples'],
            connections={
                'related_topics': ['topic1', 'topic2'],
                'likely_next_questions': ['question1']
            },
            tags=['tag1', 'tag2']
        )

        assert len(reflection.key_insights) == 2
        assert len(reflection.tags) == 2
        assert 'topic1' in reflection.connections['related_topics']
