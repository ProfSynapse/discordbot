"""
Location: /mnt/f/Code/discordbot/utils/text_formatting.py
Summary: Text formatting utilities for Discord messages.
         Handles splitting long responses, truncation, and embed creation.

Used by: main.py for formatting bot responses to fit Discord's message limits.
         Can be imported by any module that needs to format Discord content.
"""

import re
from typing import List, Optional

import discord


def create_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[discord.Color] = None
) -> discord.Embed:
    """Create a Discord embed with the given parameters.

    A convenience function for creating embeds with consistent defaults.

    Args:
        title: Optional title for the embed.
        description: Optional description/body text for the embed.
        color: Optional color for the embed sidebar. Defaults to Discord's default.

    Returns:
        A configured discord.Embed object.
    """
    embed = discord.Embed(color=color or discord.Color.default())
    if title:
        embed.title = title
    if description:
        embed.description = description
    return embed


def split_response(text: str, max_length: int = 2000) -> List[str]:
    """Split a response into chunks that fit within Discord's message limit.

    Splits intelligently at natural text boundaries, trying in order:
    1. Double newlines (paragraph boundaries)
    2. Single newlines
    3. Sentence boundaries ('. ', '! ', '? ')
    4. Hard split at max_length with '...' continuation marker

    Preserves markdown code blocks by avoiding splits inside them when
    possible.

    Args:
        text: The full response text to split.
        max_length: Maximum characters per chunk (default 2000, Discord's limit).

    Returns:
        List of strings, each within max_length.
    """
    if not text:
        return [""]

    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Find the best split point within max_length
        candidate = remaining[:max_length]

        # Avoid splitting inside a code block. Find all code block fences
        # (```) in the candidate and check if we're inside an open block.
        fence_positions = [m.start() for m in re.finditer(r'```', candidate)]
        inside_code_block = len(fence_positions) % 2 == 1  # odd = unclosed

        if inside_code_block:
            # Try to split before the last opening fence so the code block
            # stays intact in the next chunk.
            last_fence = fence_positions[-1]
            if last_fence > max_length // 4:
                # Only use this if the fence is reasonably far into the text
                # to avoid tiny chunks.
                candidate = remaining[:last_fence]

        split_point = len(candidate)

        # Strategy 1: Split on double newline (paragraph boundary)
        para_break = candidate.rfind('\n\n')
        if para_break > max_length // 4:
            split_point = para_break + 2  # include the double newline
        else:
            # Strategy 2: Split on single newline
            line_break = candidate.rfind('\n')
            if line_break > max_length // 4:
                split_point = line_break + 1
            else:
                # Strategy 3: Split on sentence boundary
                sentence_end = max(
                    candidate.rfind('. '),
                    candidate.rfind('! '),
                    candidate.rfind('? '),
                )
                if sentence_end > max_length // 4:
                    split_point = sentence_end + 2  # include the punctuation and space
                else:
                    # Strategy 4: Hard split with continuation marker
                    split_point = max_length - 3  # room for '...'
                    chunks.append(remaining[:split_point] + '...')
                    remaining = remaining[split_point:]
                    continue

        chunks.append(remaining[:split_point].rstrip())
        remaining = remaining[split_point:].lstrip('\n')

    return chunks if chunks else [""]


def truncate_response(text: str, max_length: int = 2000) -> str:
    """Truncate a response to fit within Discord's message limit.

    This is a safety net for cases where splitting is not appropriate
    (e.g., embed descriptions). Attempts to break at the last sentence
    boundary before the limit. Falls back to a hard truncation with an
    ellipsis indicator if no sentence boundary is found.

    Args:
        text: The full response text.
        max_length: Maximum allowed characters (default 2000 for plain messages).

    Returns:
        The original text if within limits, or a truncated version with '...' appended.
    """
    if len(text) <= max_length:
        return text

    # Reserve space for the truncation indicator
    truncation_indicator = "..."
    limit = max_length - len(truncation_indicator)
    truncated = text[:limit]

    # Try to break at the last sentence-ending punctuation (. ! ?)
    last_sentence_end = max(
        truncated.rfind('. '),
        truncated.rfind('! '),
        truncated.rfind('? '),
        truncated.rfind('.\n'),
        truncated.rfind('!\n'),
        truncated.rfind('?\n'),
    )

    if last_sentence_end > limit // 2:
        # Found a reasonable sentence boundary in the latter half of the text
        truncated = truncated[:last_sentence_end + 1]

    return truncated + truncation_indicator
