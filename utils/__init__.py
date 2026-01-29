"""
Location: /mnt/f/Code/discordbot/utils/__init__.py
Summary: Utils package for Discord bot utility functions and constants.
         Contains reusable components extracted from main.py for better modularity.

Used by: main.py and other modules needing text formatting, constants, or decorators.
"""

from utils.constants import MAX_PROMPT_LENGTH, MAX_CONTEXT_CHARS, THINKING_PHRASES
from utils.decorators import with_error_handling
from utils.text_formatting import split_response, truncate_response, create_embed

__all__ = [
    "MAX_PROMPT_LENGTH",
    "MAX_CONTEXT_CHARS",
    "THINKING_PHRASES",
    "with_error_handling",
    "split_response",
    "truncate_response",
    "create_embed",
]
