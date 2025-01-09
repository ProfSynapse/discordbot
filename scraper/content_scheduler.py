import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from scraper.news_scraper import scrape_all_sites  # Changed from relative import
import re
import discord
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from config import config  # Changed from relative import
import html  # Add this import at the top
from google.oauth2.credentials import Credentials
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContentScheduler:
    YOUTUBE_CHANNELS = {
        "AIExplained": "UCNJ1Ymd5yFuUPtn21xtRbbw", 
        "OpenAI": "UCXZCJLdBC09xxGZ6gcdrc6A",
        "GoogleDeepMind": "UCP7jMXSY2xbc3KCAE0MHQ-A",
        "SynapticLabs": "UCpQ8UQIEQ47AyLx__M-NTig",
        "GodaGo": "UCrWUuwQOvfBYi0JQzigbr_g",
        "Anthropic": "UCrDwWp7EBBv4NwvScIpBDOA",
        "WesRoth":"UCqcbQf6yw5KzRoDDcZ_wBSw"
    }
    
    def __init__(self, bot, news_channel_id: int, youtube_channel_id: int):
        self.bot = bot
        self.news_channel_id = news_channel_id
        self.youtube_channel_id = youtube_channel_id
        self.news_queue: List[Dict[str, Any]] = []  # Separate queue for news
        self.youtube_queue: List[Dict[str, Any]] = []  # Separate queue for YouTube
        self.articles_queue = []  # Remove this or keep for backwards compatibility
        self.running = False
        self._schedule_task = None
        self._news_drip_task = None
        self._youtube_drip_task = None
        self.seen_videos_file = 'seen_videos.json'
        self.seen_videos = self._load_seen_videos()
        self.news_channel = None
        self.youtube_channel = None
        self.scraped_urls = set()  # Moved here from news_scraper.py
        self.youtube = build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY)
        self.posted_urls = set()  # Add this line to track posted URLs

    async def start(self) -> None:
        """Initialize and start the content scheduler."""
        try:
            self._initialize_channels()
            self.running = True
            
            # Check last 100 messages in both channels
            self.seen_videos = self._load_seen_videos()
            
            # Add check of recent YouTube posts
            async for message in self.youtube_channel.history(limit=100):
                if message.embeds:
                    for embed in message.embeds:
                        if embed.url:
                            self.seen_videos.add(embed.url)
                            logger.info(f"Found existing video: {embed.url}")
            
            logger.info(f"Loaded {len(self.seen_videos)} previously posted videos")
            
            # Check last 100 messages in the channel to build initial posted_urls set
            async for message in self.news_channel.history(limit=100):
                urls = [word for word in message.content.split() 
                       if word.startswith(("http://", "https://"))]
                self.posted_urls.update(urls)
                
            logger.info(f"Loaded {len(self.posted_urls)} previously posted URLs")
            
            # Post first news article if available
            await self._fetch_content()
            if self.news_queue:
                article = self.news_queue.pop(0)
                try:
                    message = await self.news_channel.send(article['url'])
                    await message.add_reaction("📥")
                    self.posted_urls.add(article['url'])
                    logger.info(f"Posted startup article URL: {article['url']}")
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
                    message = await self.youtube_channel.send(embed=embed)
                    await message.add_reaction("📥")
                    logger.info(f"Posted startup YouTube video: {video['title']}")
                except Exception as e:
                    logger.error(f"Failed to post startup video: {e}")
                    self.youtube_queue.insert(0, video)
            
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
        """Start separate tasks for news and YouTube content"""
        self._schedule_task = asyncio.create_task(self._schedule_content())
        self._news_drip_task = asyncio.create_task(self._drip_news())
        self._youtube_drip_task = asyncio.create_task(self._drip_youtube())
        asyncio.create_task(self._monitor_tasks())

    async def stop(self) -> None:
        self._save_seen_videos()  # Save seen videos before stopping
        self.running = False
        for task in [self._schedule_task, self._news_drip_task, self._youtube_drip_task]:
            if task:
                task.cancel()

    async def _fetch_youtube_videos(self) -> int:
        """Fetch recent YouTube videos using YouTube Data API."""
        youtube_count = 0
        
        try:
            for channel_name, channel_id in self.YOUTUBE_CHANNELS.items():
                try:
                    # Create the search request
                    request = self.youtube.search().list(
                        part="snippet",
                        channelId=channel_id,
                        order="date",
                        maxResults=5,
                        type="video"
                    )
                    
                    # Execute the request in a thread pool
                    response = await asyncio.get_event_loop().run_in_executor(
                        None, request.execute
                    )
                    
                    for item in response.get('items', []):
                        try:
                            video_id = item['id']['videoId']
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                            
                            # Skip if already seen
                            if video_url in self.seen_videos:
                                continue
                            
                            # Get published time
                            published = datetime.fromisoformat(
                                item['snippet']['publishedAt'].replace('Z', '+00:00')
                            )
                            
                            # Check if recent
                            if not self._is_recent(published):
                                continue
                            
                            self.youtube_queue.append({  # Use youtube_queue instead of articles_queue
                                'type': 'youtube',
                                'title': html.unescape(item['snippet']['title']),  # Decode HTML entities
                                'url': video_url,
                                'author': channel_name,
                                'thumbnail_url': item['snippet']['thumbnails']['high']['url'],
                                'published': published.isoformat()
                            })
                            self.seen_videos.add(video_url)
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
        except:
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
        # Convert date to YYYY-MM-DD format
        try:
            date = datetime.fromisoformat(article.get('published', ''))
            date_str = date.strftime('%Y-%m-%d')
        except:
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
        """Fetch both news articles and YouTube videos into separate queues"""
        try:
            # Fetch news articles
            logger.info("Fetching news articles...")
            new_articles = await scrape_all_sites()
            # Use unified filter:
            filtered_articles = [a for a in new_articles if self._is_new_and_recent(a)]
            if filtered_articles:
                random.shuffle(filtered_articles)
                self.news_queue.extend(filtered_articles)
                logger.info(f"Added {len(filtered_articles)} filtered articles to news queue")
            
            # Fetch YouTube videos
            youtube_count = await self._fetch_youtube_videos()
            logger.info(f"Added {youtube_count} recent YouTube videos to YouTube queue")
            
        except Exception as e:
            logger.error(f"Error during content fetch: {e}", exc_info=True)

    async def _drip_news(self):
        """Distribute news articles evenly across the time window until next fetch"""
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
                        
                        if self.news_channel and self.news_queue:
                            article = self.news_queue.pop(0)
                            
                            # Skip if already posted
                            if article['url'] in self.posted_urls:
                                logger.debug(f"Skipping already posted article: {article['url']}")
                                continue
                                
                            try:
                                # Simply post the URL
                                message = await self.news_channel.send(article['url'])
                                await message.add_reaction("📥")
                                self.posted_urls.add(article['url'])  # Add URL to posted set
                                logger.info(f"Posted article: {article['url']}")
                            except Exception as e:
                                logger.error(f"Failed to post article: {e}")
                                # Only add back to queue if it wasn't a duplicate
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
        """Distribute YouTube videos evenly across the time window until next fetch"""
        while self.running:
            try:
                if self.youtube_queue:
                    # Calculate time until next fetch (roughly 12 hours)
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
                        # Calculate average delay between posts
                        base_delay = time_window / items_to_post
                        
                        # Add randomness but keep within reasonable bounds
                        delay = random.uniform(base_delay * 0.7, base_delay * 1.3)
                        logger.info(f"YouTube: Waiting {delay/60:.1f} minutes until next post")
                        
                        await asyncio.sleep(delay)
                        
                        if self.youtube_channel and self.youtube_queue:
                            video = self.youtube_queue.pop(0)
                            
                            # Skip if already seen
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
                                message = await self.youtube_channel.send(embed=embed)
                                await message.add_reaction("📥")  # Add “inbox tray” reaction
                                self.seen_videos.add(video['url'])
                                self._save_seen_videos()  # Save after successful post
                                logger.info(f"Posted YouTube video: {video['title']}")
                            except Exception as e:
                                logger.error(f"Failed to post video: {e}")
                                if video['url'] not in self.seen_videos:
                                    self.youtube_queue.insert(0, video)
                    else:
                        await asyncio.sleep(300)  # Check every 5 minutes if queue empty
                else:
                    await asyncio.sleep(300)
                    
            except Exception as e:
                logger.error(f"Error in YouTube drip: {e}")
                await asyncio.sleep(300)

    async def _monitor_tasks(self):
        """Monitor all tasks for errors and restart if needed."""
        while self.running:
            try:
                tasks = [
                    (self._schedule_task, self._schedule_content),
                    (self._news_drip_task, self._drip_news),
                    (self._youtube_drip_task, self._drip_youtube)
                ]
                
                for task, restart_func in tasks:
                    if task and task.done() and not task.cancelled():
                        if task.exception():
                            logger.error(f"Task failed: {task.exception()}")
                            # Restart failed task
                            if task == self._schedule_task:
                                self._schedule_task = asyncio.create_task(restart_func())
                            elif task == self._news_drip_task:
                                self._news_drip_task = asyncio.create_task(restart_func())
                            elif task == self._youtube_drip_task:
                                self._youtube_drip_task = asyncio.create_task(restart_func())
                                
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(60)

    def _load_seen_videos(self) -> set:
        """Load previously seen videos from file."""
        try:
            if os.path.exists(self.seen_videos_file):
                with open(self.seen_videos_file, 'r') as f:
                    return set(json.load(f))
            return set()
        except Exception as e:
            logger.error(f"Error loading seen videos: {e}")
            return set()

    def _save_seen_videos(self) -> None:
        """Save seen videos to file."""
        try:
            with open(self.seen_videos_file, 'w') as f:
                json.dump(list(self.seen_videos), f)
        except Exception as e:
            logger.error(f"Error saving seen videos: {e}")

    # ...rest of existing code...
