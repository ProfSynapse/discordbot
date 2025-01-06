import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .news_scraper import scrape_all_sites
from pytube import Channel, YouTube
import re
import discord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ContentScheduler:
    def __init__(self, bot, news_channel_id: int, youtube_channel_id: int):
        self.bot = bot
        self.news_channel_id = news_channel_id
        self.youtube_channel_id = youtube_channel_id
        self.articles_queue: List[Dict[str, Any]] = []
        self.running = False
        self._schedule_task = None
        self._drip_task = None
        self.seen_videos = set()
        
        # YouTube channels to monitor with their full URLs
        self.youtube_channels = [
            "https://www.youtube.com/c/AIExplained-Official",
            "https://www.youtube.com/c/OpenAI",
            "https://www.youtube.com/c/GoogleDeepMind",
            "https://www.youtube.com/c/SynapticLabs",
        ]
        
        logger.info(f"Initializing ContentScheduler")
        self.news_channel = None
        self.youtube_channel = None

    async def start(self):
        """Start the scheduling loop"""
        try:
            logger.info("Starting ContentScheduler")
            
            # Verify channel access
            self.news_channel = self.bot.get_channel(self.news_channel_id)
            self.youtube_channel = self.bot.get_channel(self.youtube_channel_id)
            
            if not self.news_channel or not self.youtube_channel:
                raise ValueError("One or more channels not found")
            
            self.running = True
            
            # Perform initial content fetch
            logger.info("Performing initial content fetch...")
            await self._fetch_all_content()
            logger.info(f"Initial fetch complete. Queue size: {len(self.articles_queue)}")
            
            # Start content scheduling tasks
            logger.info("Starting scheduler tasks...")
            self._schedule_task = asyncio.create_task(self._schedule_content())
            self._drip_task = asyncio.create_task(self._drip_content())
            
            # Monitor tasks for errors
            asyncio.create_task(self._monitor_tasks())
            logger.info("Scheduler tasks started successfully")
            
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}", exc_info=True)
            self.running = False
            raise

    async def stop(self):
        """Stop the scheduling loop"""
        logger.info("Stopping scheduler...")
        self.running = False
        if self._schedule_task:
            self._schedule_task.cancel()
        if self._drip_task:
            self._drip_task.cancel()

    async def _monitor_tasks(self):
        """Monitor background tasks for errors"""
        while self.running:
            try:
                for task in [self._schedule_task, self._drip_task]:
                    if task and task.done() and not task.cancelled():
                        if task.exception():
                            logger.error(f"Task failed: {task.exception()}")
                            # Restart failed task
                            if task == self._schedule_task:
                                self._schedule_task = asyncio.create_task(self._schedule_content())
                            elif task == self._drip_task:
                                self._drip_task = asyncio.create_task(self._drip_content())
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(60)

    async def _schedule_content(self):
        """Schedule content fetching twice daily"""
        while self.running:
            try:
                now = datetime.now()
                # Schedule for 6AM and 6PM
                next_run = now.replace(hour=18 if now.hour >= 6 and now.hour < 18 else 6,
                                     minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                await asyncio.sleep((next_run - now).seconds)
                if self.running:
                    await self._fetch_all_content()
            except Exception as e:
                logger.error(f"Error in content scheduler: {e}")
                await asyncio.sleep(300)

    async def _fetch_all_content(self):
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
            logger.info("Fetching YouTube videos...")
            youtube_count = 0
            
            for channel_url in self.youtube_channels:
                try:
                    logger.info(f"Fetching from channel: {channel_url}")
                    
                    try:
                        # Try different URL formats if one fails
                        channel = None
                        urls_to_try = [
                            channel_url,  # Original URL
                            channel_url.replace("/c/", "/@"),  # Try handle format
                            channel_url.replace("/c/", "/user/")  # Try legacy format
                        ]
                        
                        for url in urls_to_try:
                            try:
                                channel = Channel(url)
                                if channel:
                                    logger.info(f"Successfully connected to channel: {channel.channel_name}")
                                    break
                            except Exception as e:
                                logger.debug(f"Failed with URL {url}: {e}")
                                continue
                        
                        if not channel:
                            raise ValueError("Could not connect to channel with any URL format")
                        
                        videos = []
                        # Get recent videos
                        for video in channel.videos:
                            try:
                                # Check if video is recent (last 24 hours)
                                if self._is_recent(video.publish_date):
                                    videos.append(video)
                                    if len(videos) >= 5:  # Limit to 5 recent videos per channel
                                        break
                            except Exception as e:
                                logger.error(f"Error processing video {video.watch_url}: {e}")
                                continue
                        
                        # Process found videos
                        for video in videos:
                            if video.watch_url not in self.seen_videos:
                                try:
                                    video_id = self._extract_video_id_from_url(video.watch_url)
                                    if video_id:
                                        self.articles_queue.append({
                                            'type': 'youtube',
                                            'title': video.title,
                                            'url': video.watch_url,
                                            'author': channel.channel_name,
                                            'thumbnail_url': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                                            'published': video.publish_date.isoformat()
                                        })
                                        self.seen_videos.add(video.watch_url)
                                        youtube_count += 1
                                        logger.info(f"Added video: {video.title}")
                                except Exception as e:
                                    logger.error(f"Error adding video to queue: {e}")
                                    continue
                                    
                    except Exception as e:
                        logger.error(f"Error with channel operations: {e}")
                        continue
                                    
                except Exception as e:
                    logger.error(f"Error fetching from YouTube channel {channel_url}: {e}")
                    continue
            
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

    def _fetch_channel_videos(self, channel_url: str):
        """Fetch videos from a YouTube channel"""
        try:
            channel = Channel(channel_url)
            return list(channel.videos)
        except Exception as e:
            logger.error(f"Error fetching videos from {channel_url}: {e}")
            return []

    def _extract_video_id_from_url(self, url: str) -> str:
        """Extract video ID from various YouTube URL formats"""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'youtu.be\/([0-9A-Za-z_-]{11})',
        ]
        for pattern in patterns:
            if match := re.search(pattern, url):
                return match.group(1)
        return None

    def _is_recent(self, date: datetime) -> bool:
        """Check if date is within last 24 hours"""
        return datetime.now(date.tzinfo) - date <= timedelta(hours=24)

    async def _drip_content(self):
        """Release content from queue throughout the day"""
        while self.running:
            try:
                if self.articles_queue:
                    content = self.articles_queue.pop(0)
                    logger.info(f"Posting content: {content.get('title', 'Unknown title')}")
                    
                    if content.get('type') == 'youtube':
                        # Post YouTube content
                        embed = discord.Embed(
                            title=content['title'],
                            url=content['url'],
                            description=f"New video from {content['author']}!",
                            color=discord.Color.red()
                        )
                        if content['thumbnail_url']:
                            embed.set_image(url=content['thumbnail_url'])
                        await self.youtube_channel.send(embed=embed)
                        logger.info(f"Posted YouTube video: {content['title']}")
                    else:
                        # Post news article
                        embed = self._create_news_embed(content)
                        await self.news_channel.send(embed=embed)
                        logger.info(f"Posted news article: {content['title']}")
                    
                    # Random delay between posts (30-90 minutes)
                    delay = random.randint(1800, 5400)
                    logger.info(f"Waiting {delay} seconds before next post")
                    await asyncio.sleep(delay)
                else:
                    logger.info("Content queue empty, waiting 15 minutes")
                    await asyncio.sleep(900)
                    
            except Exception as e:
                logger.error(f"Error in content drip: {e}")
                await asyncio.sleep(900)

    def _create_news_embed(self, article: Dict[str, Any]) -> discord.Embed:
        """Create Discord embed for news articles"""
        embed = discord.Embed(
            title=article['title'],
            url=article['url'],
            color=discord.Color.blue()
        )
        
        if 'summary' in article:
            # Clean up and format summary
            summary = article['summary']
            
            # Truncate if too long, keeping complete sentences
            if len(summary) > 1000:
                # Find the last period within the first 1000 characters
                last_period = summary[:1000].rfind('.')
                if last_period > 0:
                    summary = summary[:last_period + 1] + "..."
                else:
                    summary = summary[:997] + "..."
            
            embed.description = summary.strip()
        
        if 'image_url' in article and article['image_url']:
            embed.set_image(url=article['image_url'])
            
        source = article.get('source', 'Unknown source')
        date_str = article.get('published', 'Unknown date')
        if isinstance(date_str, str) and date_str.endswith('+00:00'):
            date_str = date_str[:-6]  # Remove timezone for cleaner display
            
        embed.set_footer(text=f"Published {date_str} • {source}")
        
        return embed
