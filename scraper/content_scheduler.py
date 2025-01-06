import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .news_scraper import scrape_all_sites  # Add this import
from pytube import Channel, YouTube
import re
import discord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContentScheduler:
    YOUTUBE_CHANNELS = [
        "https://www.youtube.com/@AIExplained",
        "https://www.youtube.com/@OpenAI",
        "https://www.youtube.com/@GoogleDeepMind",
        "https://www.youtube.com/@SynapticLabs",
    ]
    
    def __init__(self, bot, news_channel_id: int, youtube_channel_id: int):
        self.bot = bot
        self.news_channel_id = news_channel_id
        self.youtube_channel_id = youtube_channel_id
        self.articles_queue: List[Dict[str, Any]] = []
        self.running = False
        self._schedule_task = None
        self._drip_task = None
        self.seen_videos = set()
        self.news_channel = None
        self.youtube_channel = None

    async def start(self) -> None:
        try:
            self._initialize_channels()
            self.running = True
            await self._fetch_content()  # Changed from _fetch_all_content
            self._start_tasks()
            logger.info("Scheduler started successfully")
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}", exc_info=True)
            self.running = False
            raise

    def _initialize_channels(self) -> None:
        self.news_channel = self.bot.get_channel(self.news_channel_id)
        self.youtube_channel = self.bot.get_channel(self.youtube_channel_id)
        if not self.news_channel or not self.youtube_channel:
            raise ValueError("One or more channels not found")

    def _start_tasks(self) -> None:
        self._schedule_task = asyncio.create_task(self._schedule_content())
        self._drip_task = asyncio.create_task(self._drip_content())
        asyncio.create_task(self._monitor_tasks())

    async def stop(self) -> None:
        self.running = False
        for task in [self._schedule_task, self._drip_task]:
            if task:
                task.cancel()

    async def _fetch_youtube_videos(self) -> int:
        youtube_count = 0
        for channel_url in self.YOUTUBE_CHANNELS:
            try:
                channel = await self._connect_to_channel(channel_url)
                if not channel:
                    continue
                
                videos = await self._get_recent_videos(channel)
                youtube_count += await self._process_videos(videos, channel)
            except Exception as e:
                logger.error(f"Error fetching from YouTube channel {channel_url}: {e}")
        return youtube_count

    async def _connect_to_channel(self, base_url: str) -> Optional[Channel]:
        urls = [
            base_url,
            base_url.replace("/c/", "/@"),
            base_url.replace("/c/", "/user/")
        ]
        
        for url in urls:
            try:
                channel = Channel(url)
                logger.info(f"Connected to channel: {channel.channel_name}")
                return channel
            except Exception as e:
                logger.debug(f"Failed with URL {url}: {e}")
        return None

    async def _get_recent_videos(self, channel: Channel) -> List[YouTube]:
        """Get recent videos from channel"""
        videos = []
        try:
            for video in channel.videos:
                if len(videos) >= 5:
                    break
                if self._is_recent(video.publish_date):
                    videos.append(video)
        except Exception as e:
            logger.error(f"Error getting videos: {e}")
        return videos

    async def _process_videos(self, videos: List[YouTube], channel: Channel) -> int:
        """Process videos and add to queue"""
        count = 0
        for video in videos:
            if video.watch_url in self.seen_videos:
                continue
                
            try:
                video_id = self._extract_video_id_from_url(video.watch_url)
                if not video_id:
                    continue
                    
                self.articles_queue.append({
                    'type': 'youtube',
                    'title': video.title,
                    'url': video.watch_url,
                    'author': channel.channel_name,
                    'thumbnail_url': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    'published': video.publish_date.isoformat()
                })
                self.seen_videos.add(video.watch_url)
                count += 1
                logger.info(f"Added video: {video.title}")
            except Exception as e:
                logger.error(f"Error processing video: {e}")
        return count

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
        return datetime.now(date.tzinfo) - date <= timedelta(hours=24)

    def _create_news_embed(self, article: Dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=article['title'],
            url=article['url'],
            color=discord.Color.blue()
        )
        
        if 'summary' in article:
            embed.description = self._format_summary(article['summary'])
            
        if article.get('image_url'):
            embed.set_image(url=article['image_url'])
            
        source = article.get('source', 'Unknown source')
        date_str = self._format_date(article.get('published', 'Unknown date'))
        embed.set_footer(text=f"Published {date_str} • {source}")
        
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

    async def _schedule_content(self):
        """Schedule content fetching twice daily"""
        while self.running:
            try:
                now = datetime.now()
                next_run = now.replace(hour=18 if now.hour >= 6 and now.hour < 18 else 6,
                                     minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                await asyncio.sleep((next_run - now).seconds)
                if self.running:
                    await self._fetch_content()  # Changed from _fetch_all_content
            except Exception as e:
                logger.error(f"Error in content scheduler: {e}")
                await asyncio.sleep(300)

    async def _fetch_content(self):  # Renamed from _fetch_all_content
        """Fetch both news articles and YouTube videos"""
        try:
            # Fetch news articles
            logger.info("Fetching news articles...")
            new_articles = await scrape_all_sites()
            
            # Filter for recent articles
            recent_articles = [
                article for article in new_articles
                if self._is_recent(datetime.fromisoformat(article['published']))
            ]
            
            if recent_articles:
                random.shuffle(recent_articles)
                self.articles_queue.extend(recent_articles)
                logger.info(f"Added {len(recent_articles)} recent news articles to queue")
            else:
                logger.warning("No recent news articles found")
            
            # Fetch YouTube videos
            youtube_count = await self._fetch_youtube_videos()
            logger.info(f"Added {youtube_count} recent YouTube videos to queue")
            
            # Sort all content by date
            if self.articles_queue:
                self.articles_queue.sort(
                    key=lambda x: datetime.fromisoformat(x.get('published', datetime.now().isoformat())),
                    reverse=True
                )
                logger.info(f"Total recent items in queue after fetch: {len(self.articles_queue)}")
            
        except Exception as e:
            logger.error(f"Error during content fetch: {e}", exc_info=True)
