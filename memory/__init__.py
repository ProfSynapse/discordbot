"""
Location: /mnt/f/Code/discordbot/memory/__init__.py
Summary: Conversational memory pipeline package. Tracks Discord conversations,
         detects topic shifts, generates reflective summaries, and outputs in
         dual formats (JSONL for fine-tuning, Markdown for RAG).

Used by: main.py (imports ConversationMemoryPipeline)
"""

from memory.models import (
    ConversationMessage,
    ChunkMetadata,
    TopicShiftResult,
    Reflection,
    ConversationChunk
)
from memory.buffer import ConversationBuffer
from memory.detector import TopicDetector
from memory.summarizer import ConversationSummarizer
from memory.packager import ChunkPackager
from memory.uploader import MemoryUploader
from memory.pipeline import ConversationMemoryPipeline

__all__ = [
    # Models
    'ConversationMessage',
    'ChunkMetadata',
    'TopicShiftResult',
    'Reflection',
    'ConversationChunk',
    # Components
    'ConversationBuffer',
    'TopicDetector',
    'ConversationSummarizer',
    'ChunkPackager',
    'MemoryUploader',
    # Pipeline
    'ConversationMemoryPipeline'
]
