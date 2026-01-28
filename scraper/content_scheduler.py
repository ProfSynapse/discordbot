"""
scraper/content_scheduler.py

Schedules and distributes AI-related content (YouTube videos and news articles) to a
Discord channel on a drip-feed basis. Content is fetched twice daily (6 AM and 6 PM) and
posted at randomized intervals to maintain a natural posting cadence.

Persistence: Uses SQLite (shared with session_manager via config.SESSION_DB_PATH) to
track previously seen videos and posted article URLs. In-memory sets are used as caches
for fast lookups, backed by the `seen_content` table in the database.

Related files:
  - scraper/news_scraper.py: Provides scrape_all_sites() for RSS article fetching
  - scraper/content_scraper.py: Provides article content extraction (unused here directly)
  - config.py: Supplies SESSION_DB_PATH, YOUTUBE_API_KEY, and other settings
  - session_manager.py: Uses the same SQLite database for session persistence
  - api_client.py: GPT Trainer API client for uploading content to knowledge base
"""

import asyncio
import random
import logging
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from scraper.news_scraper import scrape_all_sites
import re
import discord
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from config import config
import html
from google.oauth2.credentials import Credentials
from api_client import api_client

logger = logging.getLogger(__name__)

# Number of days after which old seen_content entries are purged during startup cleanup.
_SEEN_CONTENT_MAX_AGE_DAYS = 90


class ContentScheduler:
    """Fetches, queues, and drip-posts YouTube videos and news articles to Discord.

    Persistence is handled via a `seen_content` table in the project's shared SQLite
    database (config.SESSION_DB_PATH). In-memory sets (`seen_videos`, `posted_urls`)
    serve as caches; every mutation is written through to the database.
    """

    YOUTUBE_CHANNELS = {
        "SynapticLabs": "UCpQ8UQIEQ47AyLx__M-NTig",
    }

    def __init__(self, bot, content_channel_id: int):
        self.bot = bot
        self.content_channel_id = content_channel_id
        self.news_queue: List[Dict[str, Any]] = []
        self.youtube_queue: List[Dict[str, Any]] = []
        self.articles_queue = []  # Kept for backwards compatibility
        self.running = False
        self._schedule_task = None
        self._news_drip_task = None
        self._youtube_drip_task = None
        self._youtube_kb_sync_task = None
        # In-memory caches backed by SQLite seen_content table
        self.seen_videos: set = set()
        self.posted_urls: set = set()
        self.content_channel = None
        self.scraped_urls = set()
        self.youtube = build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY)
        self._db_path = config.SESSION_DB_PATH

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    async def _init_db(self) -> None:
        """Create the seen_content table if it does not already exist.

        The table lives in the same SQLite database used by session_manager
        (config.SESSION_DB_PATH) so that all persistence is consolidated in
        a single file on the persistent volume.
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS seen_content (
                    url TEXT PRIMARY KEY,
                    content_type TEXT NOT NULL,
                    first_seen TEXT NOT NULL
                )
            """)
            await db.commit()
        logger.info("seen_content table initialized")

    async def _load_seen_content_from_db(self) -> None:
        """Populate in-memory caches from the database."""
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT url, content_type FROM seen_content"
            ) as cursor:
                rows = await cursor.fetchall()
                for url, content_type in rows:
                    if content_type == "video":
                        self.seen_videos.add(url)
                    elif content_type == "article":
                        self.posted_urls.add(url)
        logger.info(
            f"Loaded from DB: {len(self.seen_videos)} seen videos, "
            f"{len(self.posted_urls)} posted URLs"
        )

    async def _add_seen_content(self, url: str, content_type: str) -> None:
        """Write a URL to both the in-memory cache and the database.

        Args:
            url: The content URL.
            content_type: Either 'video' or 'article'.
        """
        # Update in-memory cache first
        if content_type == "video":
            self.seen_videos.add(url)
        else:
            self.posted_urls.add(url)

        # Persist to database
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """INSERT OR IGNORE INTO seen_content (url, content_type, first_seen)
                       VALUES (?, ?, ?)""",
                    (url, content_type, datetime.now(timezone.utc).isoformat())
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist seen content to DB: {e}")

    async def _cleanup_old_seen_content(self) -> int:
        """Remove seen_content entries older than _SEEN_CONTENT_MAX_AGE_DAYS.

        Returns:
            Number of rows deleted.
        """
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=_SEEN_CONTENT_MAX_AGE_DAYS)
        ).isoformat()

        try:
            async with aiosqlite.connect(self._db_path) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM seen_content WHERE first_seen < ?",
                    (cutoff,)
                ) as cursor:
                    count = (await cursor.fetchone())[0]

                if count > 0:
                    await db.execute(
                        "DELETE FROM seen_content WHERE first_seen < ?",
                        (cutoff,)
                    )
                    await db.commit()
                    logger.info(f"Cleaned up {count} old seen_content entries (>{_SEEN_CONTENT_MAX_AGE_DAYS} days)")

                return count
        except Exception as e:
            logger.warning(f"Error cleaning up old seen content: {e}")
            return 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize and start the content scheduler."""
        try:
            self._initialize_channels()
            self.running = True

            # Initialize database table and clean up stale entries (F7)
            await self._init_db()
            await self._cleanup_old_seen_content()

            # Load persisted seen content into in-memory caches
            await self._load_seen_content_from_db()

            # M7 fix: single loop over channel history populates both caches
            async for message in self.content_channel.history(limit=100):
                # Check embeds for YouTube video URLs
                if message.embeds:
                    for embed in message.embeds:
                        if embed.url:
                            if embed.url not in self.seen_videos:
                                await self._add_seen_content(embed.url, "video")
                                logger.info(f"Found existing video: {embed.url}")

                # Check message content for plain-text URLs (articles)
                urls = [
                    word for word in message.content.split()
                    if word.startswith(("http://", "https://"))
                ]
                for url in urls:
                    if url not in self.posted_urls:
                        await self._add_seen_content(url, "article")

            logger.info(
                f"After channel scan: {len(self.seen_videos)} seen videos, "
                f"{len(self.posted_urls)} posted URLs"
            )

            # Post first news article if available
            await self._fetch_content()
            if self.news_queue:
                article = self.news_queue.pop(0)
                try:
                    message = await self.content_channel.send(article['url'])
                    await self._add_seen_content(article['url'], "article")
                    logger.info(f"Posted startup article URL: {article['url']}")
                    await self._upload_to_gpt_trainer(article['url'], 'article')
                except Exception as e:
                    logger.error(f"Failed to post startup article: {e}")
                    self.news_queue.insert(0, article)

            # Post first YouTube video if available
            if self.youtube_queue:
                video = self.youtube_queue.pop(0)
                try:
                    embed = discord.Embed(
                        title=video['title'],
                        url=video['url'],
                        color=discord.Color.red()
                    )
                    embed.set_image(url=video['thumbnail_url'])
                    embed.set_footer(text=f"Posted by {video['author']}")
                    message = await self.content_channel.send(embed=embed)
                    await self._add_seen_content(video['url'], "video")
                    logger.info(f"Posted startup YouTube video: {video['title']}")
                    await self._upload_to_gpt_trainer(video['url'], 'video')
                except Exception as e:
                    logger.error(f"Failed to post startup video: {e}")
                    self.youtube_queue.insert(0, video)

            # TODO: Remove after first deploy — one-time reset for video backfill retry
            logger.info("One-time cleanup: clearing seen video entries for backfill retry")
            async with aiosqlite.connect(config.SESSION_DB_PATH) as db:
                await db.execute("DELETE FROM seen_content WHERE content_type = 'video'")
                await db.commit()
            self.seen_videos.clear()

            # Backfill all historical SynapticLabs videos into GPT Trainer
            # knowledge base. Idempotent -- already-seen videos are skipped.
            await self.backfill_youtube_videos()

            self._start_tasks()
            logger.info("Scheduler started successfully")

        except Exception as e:
            logger.error(f"Error starting scheduler: {e}", exc_info=True)
            self.running = False
            raise

    def _initialize_channels(self) -> None:
        self.content_channel = self.bot.get_channel(self.content_channel_id)
        if not self.content_channel:
            raise ValueError("Content channel not found")

    def _start_tasks(self) -> None:
        """Start separate tasks for news and YouTube content."""
        self._schedule_task = asyncio.create_task(self._schedule_content())
        self._news_drip_task = asyncio.create_task(self._drip_news())
        self._youtube_drip_task = asyncio.create_task(self._drip_youtube())
        self._youtube_kb_sync_task = asyncio.create_task(self._schedule_youtube_kb_sync())
        asyncio.create_task(self._monitor_tasks())

    async def stop(self) -> None:
        """Stop the scheduler gracefully, awaiting cancelled tasks (F8)."""
        self.running = False
        tasks_to_cancel = [
            task for task in
            [self._schedule_task, self._news_drip_task, self._youtube_drip_task,
             self._youtube_kb_sync_task]
            if task is not None
        ]
        for task in tasks_to_cancel:
            task.cancel()

        # F8: await cancelled tasks so they can clean up properly
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        logger.info("Scheduler stopped")

    # ------------------------------------------------------------------
    # YouTube fetching
    # ------------------------------------------------------------------

    async def _fetch_youtube_videos(self) -> int:
        """Fetch YouTube videos from the last 7 days using YouTube Data API.

        Uses the `publishedAfter` parameter to look back 7 days instead of
        relying on the 24-hour `_is_recent()` filter. This prevents videos
        from being lost if the bot misses a fetch cycle. The `seen_videos`
        set still prevents duplicate posts.
        """
        youtube_count = 0
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            for channel_name, channel_id in self.YOUTUBE_CHANNELS.items():
                try:
                    request = self.youtube.search().list(
                        part="snippet",
                        channelId=channel_id,
                        order="date",
                        maxResults=25,
                        type="video",
                        publishedAfter=published_after
                    )

                    # M6 fix: use get_running_loop() instead of deprecated get_event_loop()
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, request.execute)

                    for item in response.get('items', []):
                        try:
                            video_id = item['id']['videoId']
                            video_url = f"https://www.youtube.com/watch?v={video_id}"

                            if video_url in self.seen_videos:
                                continue

                            published = datetime.fromisoformat(
                                item['snippet']['publishedAt'].replace('Z', '+00:00')
                            )

                            self.youtube_queue.append({
                                'type': 'youtube',
                                'title': html.unescape(item['snippet']['title']),
                                'url': video_url,
                                'author': channel_name,
                                'thumbnail_url': item['snippet']['thumbnails']['high']['url'],
                                'published': published.isoformat()
                            })
                            await self._add_seen_content(video_url, "video")
                            youtube_count += 1
                            logger.info(f"Added video: {item['snippet']['title']}")

                        except Exception as e:
                            logger.error(f"Error processing video: {str(e)}")
                            continue

                except HttpError as e:
                    logger.error(f"YouTube API error for channel {channel_name}: {str(e)}")
                    continue
                except Exception as e:
                    logger.error(f"Error fetching from channel {channel_name}: {str(e)}")
                    continue

            logger.info(f"Successfully fetched {youtube_count} YouTube videos")
            return youtube_count

        except Exception as e:
            logger.error(f"Error in _fetch_youtube_videos: {str(e)}", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_video_id_from_url(self, url: str) -> Optional[str]:
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu.be\/([0-9A-Za-z_-]{11})'
        ]
        for pattern in patterns:
            if match := re.search(pattern, url):
                return match.group(1)
        return None

    def _is_recent(self, date: datetime) -> bool:
        """Check if a date is within the last 24 hours."""
        return datetime.now(date.tzinfo) - date <= timedelta(hours=24)

    def _is_new_and_recent(self, article: Dict[str, Any], hours: int = 24) -> bool:
        """Check if an article is both new (not posted) and recent."""
        try:
            published = datetime.fromisoformat(article['published'])
            recent_enough = (datetime.now(published.tzinfo) - published) <= timedelta(hours=hours)
            not_posted = article['url'] not in self.posted_urls
            return recent_enough and not_posted
        except Exception as e:
            # M4 fix: catch Exception instead of bare except
            logger.warning(f"Error checking if article is new/recent: {e}")
            return False

    def _create_news_embed(self, article: Dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=article['title'],
            url=article['url'],
            color=discord.Color.blue()
        )

        if 'summary' in article:
            embed.description = self._format_summary(article['summary'])

        source = article.get('source', 'Unknown source')
        try:
            date = datetime.fromisoformat(article.get('published', ''))
            date_str = date.strftime('%Y-%m-%d')
        except Exception as e:
            # M4 fix: catch Exception instead of bare except
            logger.warning(f"Error formatting article date: {e}")
            date_str = 'Unknown date'

        embed.set_footer(text=f"{date_str} • {source}")
        return embed

    def _format_summary(self, summary: str) -> str:
        if len(summary) <= 1000:
            return summary.strip()

        last_period = summary[:1000].rfind('.')
        if last_period > 0:
            return summary[:last_period + 1] + "..."
        return summary[:997] + "..."

    def _format_date(self, date_str: str) -> str:
        if isinstance(date_str, str) and date_str.endswith('+00:00'):
            return date_str[:-6]
        return date_str

    # ------------------------------------------------------------------
    # Scheduling and drip-feed loops
    # ------------------------------------------------------------------

    async def _schedule_content(self):
        """Schedule content fetching twice daily (6 AM and 6 PM)."""
        while self.running:
            try:
                now = datetime.now()
                next_run = now.replace(
                    hour=18 if now.hour >= 6 and now.hour < 18 else 6,
                    minute=0, second=0, microsecond=0
                )
                if next_run <= now:
                    next_run += timedelta(days=1)

                # M11 fix: use .total_seconds() instead of .seconds to handle >24h spans
                await asyncio.sleep(int((next_run - now).total_seconds()))
                if self.running:
                    await self._fetch_content()
            except Exception as e:
                logger.error(f"Error in content scheduler: {e}")
                await asyncio.sleep(300)

    async def _fetch_content(self):
        """Fetch both news articles and YouTube videos into separate queues."""
        try:
            logger.info("Fetching news articles...")
            new_articles = await scrape_all_sites()
            filtered_articles = [a for a in new_articles if self._is_new_and_recent(a)]
            if filtered_articles:
                random.shuffle(filtered_articles)
                self.news_queue.extend(filtered_articles)
                logger.info(f"Added {len(filtered_articles)} filtered articles to news queue")

            youtube_count = await self._fetch_youtube_videos()
            logger.info(f"Added {youtube_count} recent YouTube videos to YouTube queue")

        except Exception as e:
            logger.error(f"Error during content fetch: {e}", exc_info=True)

    async def _drip_news(self):
        """Distribute news articles evenly across the time window until next fetch."""
        while self.running:
            try:
                if self.news_queue:
                    now = datetime.now()
                    next_fetch = now.replace(
                        hour=18 if now.hour < 18 else 6,
                        minute=0, second=0, microsecond=0
                    )
                    if next_fetch <= now:
                        next_fetch += timedelta(days=1)

                    time_window = (next_fetch - now).total_seconds()
                    items_to_post = len(self.news_queue)

                    if items_to_post > 0:
                        base_delay = time_window / items_to_post
                        delay = random.uniform(base_delay * 0.7, base_delay * 1.3)
                        logger.info(f"News: Waiting {delay/60:.1f} minutes until next post")

                        await asyncio.sleep(delay)

                        if self.content_channel and self.news_queue:
                            article = self.news_queue.pop(0)

                            if article['url'] in self.posted_urls:
                                logger.debug(f"Skipping already posted article: {article['url']}")
                                continue

                            try:
                                await self.content_channel.send(article['url'])
                                await self._add_seen_content(article['url'], "article")
                                logger.info(f"Posted article: {article['url']}")
                                await self._upload_to_gpt_trainer(article['url'], 'article')
                            except Exception as e:
                                logger.error(f"Failed to post article: {e}")
                                if article['url'] not in self.posted_urls:
                                    self.news_queue.insert(0, article)
                    else:
                        await asyncio.sleep(300)
                else:
                    await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Error in news drip: {e}")
                await asyncio.sleep(300)

    async def _drip_youtube(self):
        """Distribute YouTube videos evenly across the time window until next fetch."""
        while self.running:
            try:
                if self.youtube_queue:
                    now = datetime.now()
                    next_fetch = now.replace(
                        hour=18 if now.hour < 18 else 6,
                        minute=0, second=0, microsecond=0
                    )
                    if next_fetch <= now:
                        next_fetch += timedelta(days=1)

                    time_window = (next_fetch - now).total_seconds()
                    items_to_post = len(self.youtube_queue)

                    if items_to_post > 0:
                        base_delay = time_window / items_to_post
                        delay = random.uniform(base_delay * 0.7, base_delay * 1.3)
                        logger.info(f"YouTube: Waiting {delay/60:.1f} minutes until next post")

                        await asyncio.sleep(delay)

                        if self.content_channel and self.youtube_queue:
                            video = self.youtube_queue.pop(0)

                            if video['url'] in self.seen_videos:
                                logger.info(f"Skipping already posted video: {video['url']}")
                                continue

                            try:
                                embed = discord.Embed(
                                    title=video['title'],
                                    url=video['url'],
                                    color=discord.Color.red()
                                )
                                embed.set_image(url=video['thumbnail_url'])
                                embed.set_footer(text=f"Posted by {video['author']}")
                                message = await self.content_channel.send(embed=embed)
                                await self._add_seen_content(video['url'], "video")
                                logger.info(f"Posted YouTube video: {video['title']}")
                            except Exception as e:
                                logger.error(f"Failed to post video: {e}")
                                if video['url'] not in self.seen_videos:
                                    self.youtube_queue.insert(0, video)
                    else:
                        await asyncio.sleep(300)
                else:
                    await asyncio.sleep(300)

            except Exception as e:
                logger.error(f"Error in YouTube drip: {e}")
                await asyncio.sleep(300)

    # ------------------------------------------------------------------
    # YouTube knowledge base sync
    # ------------------------------------------------------------------

    async def _schedule_youtube_kb_sync(self):
        """Periodically sync recent SynapticLabs YouTube videos to GPT Trainer knowledge base.

        Runs independently from the Discord drip-feed. Every 24 hours, fetches
        videos published in the last 7 days and uploads any unseen ones to the
        GPT Trainer knowledge base. Videos are marked as seen but are NOT posted
        to Discord -- this task is KB-only.

        The first sync cycle runs immediately on task start; subsequent cycles
        run every 24 hours.
        """
        channel_name = "SynapticLabs"
        channel_id = self.YOUTUBE_CHANNELS.get(channel_name)
        if not channel_id:
            logger.warning(
                "SynapticLabs channel not found in YOUTUBE_CHANNELS; "
                "YouTube KB sync disabled"
            )
            return

        while self.running:
            try:
                published_after = (
                    datetime.now(timezone.utc) - timedelta(days=7)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")

                logger.info("YouTube KB sync: fetching recent SynapticLabs videos...")

                request = self.youtube.search().list(
                    part="snippet",
                    channelId=channel_id,
                    order="date",
                    maxResults=25,
                    type="video",
                    publishedAfter=published_after
                )

                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, request.execute)

                synced_count = 0
                failed_count = 0
                for item in response.get("items", []):
                    try:
                        video_id = item["id"]["videoId"]
                        video_url = f"https://www.youtube.com/watch?v={video_id}"

                        if video_url in self.seen_videos:
                            continue

                        title = html.unescape(
                            item["snippet"].get("title", "Unknown")
                        )
                        uploaded = await self._upload_to_gpt_trainer(video_url, "video")
                        if uploaded:
                            await self._add_seen_content(video_url, "video")
                            synced_count += 1
                            logger.info(f"YouTube KB sync: uploaded '{title}'")
                        else:
                            failed_count += 1
                            logger.warning(
                                f"YouTube KB sync: upload failed for '{title}' "
                                f"({video_url}); will retry on next sync cycle"
                            )

                        # Small delay between uploads to avoid rate limiting
                        await asyncio.sleep(1.5)

                    except Exception as e:
                        logger.error(
                            f"YouTube KB sync: error processing video: {e}"
                        )
                        continue

                logger.info(
                    f"YouTube KB sync complete: {synced_count} new videos "
                    f"uploaded to knowledge base, {failed_count} failed"
                )

            except HttpError as e:
                logger.error(f"YouTube KB sync: YouTube API error: {e}")
            except Exception as e:
                logger.error(
                    f"YouTube KB sync: unexpected error: {e}", exc_info=True
                )

            # Wait 24 hours before the next sync cycle
            await asyncio.sleep(86400)

    # ------------------------------------------------------------------
    # Task monitoring
    # ------------------------------------------------------------------

    async def _monitor_tasks(self):
        """Monitor all tasks for errors and restart if needed."""
        while self.running:
            try:
                tasks = [
                    (self._schedule_task, self._schedule_content),
                    (self._news_drip_task, self._drip_news),
                    (self._youtube_drip_task, self._drip_youtube),
                    (self._youtube_kb_sync_task, self._schedule_youtube_kb_sync)
                ]

                for task, restart_func in tasks:
                    if task and task.done() and not task.cancelled():
                        if task.exception():
                            logger.error(f"Task failed: {task.exception()}")
                            if task == self._schedule_task:
                                self._schedule_task = asyncio.create_task(restart_func())
                            elif task == self._news_drip_task:
                                self._news_drip_task = asyncio.create_task(restart_func())
                            elif task == self._youtube_drip_task:
                                self._youtube_drip_task = asyncio.create_task(restart_func())
                            elif task == self._youtube_kb_sync_task:
                                self._youtube_kb_sync_task = asyncio.create_task(restart_func())

                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # GPT Trainer upload
    # ------------------------------------------------------------------

    async def _upload_to_gpt_trainer(self, url: str, content_type: str) -> bool:
        """Automatically upload content to GPT Trainer knowledge base.

        Args:
            url: The URL to upload.
            content_type: Type of content ('article' or 'video').

        Returns:
            True if the upload succeeded or the content already exists,
            False otherwise.
        """
        try:
            logger.info(f"Uploading {content_type} to GPT Trainer: {url}")
            async with api_client as client:
                result = await client.upload_data_source(url)
                if result.get('success') or result.get('status') == 'existing':
                    logger.info(f"Successfully added {content_type} to knowledge base: {url}")
                    return True
                else:
                    logger.warning(
                        f"Failed to upload {content_type}: {result.get('error', 'Unknown error')} "
                        f"| raw response: {result}"
                    )
                    return False
        except Exception as e:
            logger.error(f"Error uploading {content_type} to GPT Trainer: {e}")
            # Don't raise - upload failures should not stop content posting
            return False

    # ------------------------------------------------------------------
    # YouTube backfill
    # ------------------------------------------------------------------

    async def backfill_youtube_videos(self) -> None:
        """Page through ALL SynapticLabs channel videos and upload each to GPT Trainer.

        This is a knowledge-base-only operation: videos are uploaded to GPT Trainer
        and marked as seen in the database, but are NOT posted to Discord. It is
        idempotent -- already-seen videos are skipped.

        Pagination uses the YouTube Data API `pageToken` to walk through all
        results. A small delay between uploads avoids rate limiting.
        """
        channel_name = "SynapticLabs"
        channel_id = self.YOUTUBE_CHANNELS.get(channel_name)
        if not channel_id:
            logger.warning("SynapticLabs channel not found in YOUTUBE_CHANNELS; skipping backfill")
            return

        logger.info("Starting YouTube backfill for SynapticLabs channel...")
        total_uploaded = 0
        total_skipped = 0
        total_failed = 0
        page_token = None

        try:
            while True:
                try:
                    request_kwargs = {
                        "part": "snippet",
                        "channelId": channel_id,
                        "order": "date",
                        "maxResults": 50,
                        "type": "video",
                    }
                    if page_token:
                        request_kwargs["pageToken"] = page_token

                    request = self.youtube.search().list(**request_kwargs)
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, request.execute)

                except HttpError as e:
                    logger.error(f"YouTube API error during backfill: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error fetching backfill page: {e}")
                    break

                items = response.get("items", [])
                if not items:
                    logger.info("No more videos found during backfill")
                    break

                for item in items:
                    try:
                        video_id = item["id"]["videoId"]
                        video_url = f"https://www.youtube.com/watch?v={video_id}"

                        if video_url in self.seen_videos:
                            total_skipped += 1
                            continue

                        # Upload to knowledge base (no Discord post)
                        title = html.unescape(item["snippet"].get("title", "Unknown"))
                        uploaded = await self._upload_to_gpt_trainer(video_url, "video")
                        if uploaded:
                            await self._add_seen_content(video_url, "video")
                            total_uploaded += 1
                            logger.info(
                                f"Backfilled {total_uploaded} videos "
                                f"(skipped {total_skipped}): {title}"
                            )
                        else:
                            total_failed += 1
                            logger.warning(
                                f"Backfill upload failed for '{title}' ({video_url}); "
                                f"will retry on next backfill cycle"
                            )

                        # Small delay to avoid rate limiting
                        await asyncio.sleep(1.5)

                    except Exception as e:
                        logger.error(f"Error processing backfill video: {e}")
                        continue

                # Advance to next page or stop
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            logger.info(
                f"YouTube backfill complete: {total_uploaded} uploaded, "
                f"{total_skipped} already seen, {total_failed} failed"
            )

        except Exception as e:
            logger.error(f"Error in backfill_youtube_videos: {e}", exc_info=True)
