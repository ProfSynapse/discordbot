"""
Location: /mnt/f/Code/discordbot/link_handler.py
Summary: Handles automatic URL detection and upload to GPT Trainer knowledge base.
         When users post URLs in configured channels, this module extracts them,
         checks if they've been seen before, uploads new ones to the knowledge base,
         and provides feedback via message reactions.

Used by: main.py (on_message handler)
Uses: config.py (settings), api_client.py (knowledge base upload)
"""

import re
import logging
import aiosqlite
from datetime import datetime, timezone
from typing import List
import discord
from config import config
from api_client import api_client

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')


async def extract_urls(content: str) -> List[str]:
    """Extract valid HTTP(S) URLs from message content."""
    return URL_PATTERN.findall(content)


async def is_url_seen(url: str, db_path: str) -> bool:
    """Check if URL already exists in seen_content table."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT 1 FROM seen_content WHERE url = ?", (url,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_url_seen(url: str, db_path: str) -> None:
    """Mark URL as seen in the database."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """INSERT OR IGNORE INTO seen_content (url, content_type, first_seen)
               VALUES (?, ?, ?)""",
            (url, 'user_link', datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


async def upload_urls_from_content(content: str) -> tuple[int, int]:
    """Extract and upload URLs from text content to the knowledge base.

    This is used by the @mention handler to upload URLs BEFORE processing
    the chat request, allowing the bot to immediately reference the content.

    Returns:
        Tuple of (success_count, failure_count)
    """
    import time
    start = time.monotonic()

    urls = await extract_urls(content)
    if not urls:
        logger.debug(f"[LinkHandler] no URLs found, returning early")
        return (0, 0)

    db_path = config.SESSION_DB_PATH
    new_urls = []

    for url in urls:
        if not await is_url_seen(url, db_path):
            new_urls.append(url)

    if not new_urls:
        logger.debug(f"[LinkHandler] {len(urls)} URLs found but all already seen")
        return (0, 0)

    logger.debug(f"[LinkHandler] uploading {len(new_urls)} new URLs")
    success_count = 0
    failure_count = 0

    async with api_client as client:
        for url in new_urls:
            try:
                result = await client.upload_data_source(url)
                if result.get('success') or result.get('status') in ('existing', 'await'):
                    await mark_url_seen(url, db_path)
                    success_count += 1
                    logger.info(f"[LinkHandler] uploaded to KB: {url}")
                else:
                    failure_count += 1
                    logger.warning(f"[LinkHandler] upload failed: {url} - {result.get('error', 'Unknown')}")
            except Exception as e:
                failure_count += 1
                logger.error(f"[LinkHandler] error uploading {url}: {e}")

    elapsed = time.monotonic() - start
    logger.debug(f"[LinkHandler] completed in {elapsed:.2f}s - {success_count} success, {failure_count} failed")
    return (success_count, failure_count)


async def handle_link_message(message: discord.Message) -> None:
    """Process a message for knowledge base URLs (channel-based auto-upload).

    Extracts URLs, filters already-seen ones, uploads new URLs to GPT Trainer,
    and reacts to indicate success or failure.
    """
    logger.debug(f"[LinkHandler] processing msg {message.id} in channel {message.channel.id}")
    success_count, failure_count = await upload_urls_from_content(message.content)

    if success_count == 0 and failure_count == 0:
        return  # No new URLs found

    try:
        if success_count > 0 and failure_count == 0:
            await message.add_reaction('\u2705')  # checkmark
        elif failure_count > 0:
            await message.add_reaction('\u26a0\ufe0f')  # warning
    except discord.errors.Forbidden:
        logger.warning(f"[LinkHandler] cannot react to msg {message.id} - missing permissions")
    except Exception as e:
        logger.error(f"[LinkHandler] error adding reaction: {e}")
