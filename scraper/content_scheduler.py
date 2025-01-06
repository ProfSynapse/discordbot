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
        "https://www.youtube.com/@godago",
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
        self.scraped_urls = set()  # Moved here from news_scraper.py

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
        """Fetch recent YouTube videos from configured channels."""
        youtube_count = 0
        
        try:
            for channel_url in self.YOUTUBE_CHANNELS:
                try:
                    logger.info(f"Fetching from YouTube channel: {channel_url}")
                    # Create Channel object
                    try:
                        channel = Channel(channel_url)
                        channel_name = channel.channel_name
                        logger.info(f"Connected to channel: {channel_name}")
                        
                        # Get recent videos
                        for video in channel.videos:
                            try:
                                # Check if we've seen enough videos from this channel
                                if youtube_count >= 5:
                                    break
                                    
                                # Check if video is already seen
                                if video.watch_url in self.seen_videos:
                                    continue
                                
                                # Check if video is recent (within 24 hours)
                                if not self._is_recent(video.publish_date):
                                    continue
                                
                                # Add video to queue
                                video_id = self._extract_video_id_from_url(video.watch_url)
                                if not video_id:
                                    continue
                                
                                self.articles_queue.append({
                                    'type': 'youtube',
                                    'title': video.title,
                                    'url': video.watch_url,
                                    'author': channel_name,
                                    'thumbnail_url': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                                    'published': video.publish_date.isoformat()
                                })
                                self.seen_videos.add(video.watch_url)
                                youtube_count += 1
                                logger.info(f"Added video: {video.title}")
                                
                            except Exception as e:
                                logger.error(f"Error processing video: {str(e)}")
                                continue
                                
                    except Exception as e:
                        logger.error(f"Error accessing channel {channel_url}: {str(e)}")
                        continue
                        
                except Exception as e:
                    logger.error(f"Error in channel loop for {channel_url}: {str(e)}")
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
        return datetime.now(date.tzinfo) - date <= timedelta(hours=24)

    def _is_new_and_recent(self, article: Dict[str, Any], hours: int = 24) -> bool:
        try:
            published = datetime.fromisoformat(article['published'])
            recent_enough = (datetime.now(published.tzinfo) - published) <= timedelta(hours=hours)
            not_seen = article['url'] not in self.scraped_urls
            if recent_enough and not_seen:
                self.scraped_urls.add(article['url'])
                return True
        except:
            pass
        return False

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
            # Use unified filter:
            filtered_articles = [a for a in new_articles if self._is_new_and_recent(a)]
            if filtered_articles:
                random.shuffle(filtered_articles)
                self.articles_queue.extend(filtered_articles)
                logger.info(f"Added {len(filtered_articles)} filtered articles to queue")
            
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

    async def _drip_content(self):
        """Continuously drip articles and videos to respective channels."""
        while self.running:
            try:
                if self.articles_queue:
                    content = self.articles_queue.pop(0)
                    
                    # Handle different content types
                    if content.get('type') == 'youtube':
                        # Post to YouTube channel
                        if self.youtube_channel:
                            embed = discord.Embed(
                                title=content['title'],
                                url=content['url'],
                                color=discord.Color.red()
                            )
                            embed.set_image(url=content['thumbnail_url'])
                            embed.set_footer(text=f"Posted by {content['author']}")
                            
                            try:
                                await self.youtube_channel.send(embed=embed)
                                logger.info(f"Posted YouTube video: {content['title']}")
                            except Exception as e:
                                logger.error(f"Failed to post YouTube video: {e}")
                                # Put it back in queue if failed
                                self.articles_queue.insert(0, content)
                    else:
                        # Post news article
                        if self.news_channel:
                            try:
                                embed = self._create_news_embed(content)
                                await self.news_channel.send(embed=embed)
                                logger.info(f"Posted article: {content['title']}")
                            except Exception as e:
                                logger.error(f"Failed to post article: {e}")
                                # Put it back in queue if failed
                                self.articles_queue.insert(0, content)
                    
                    await asyncio.sleep(random.randint(1800, 3600))  # between 30-60 min
                else:
                    logger.info("No content in queue; sleeping 15 minutes.")
                    await asyncio.sleep(900)
            except Exception as e:
                logger.error(f"Error in _drip_content: {e}", exc_info=True)
                await asyncio.sleep(300)

    async def _monitor_tasks(self):
        """Monitor background tasks for errors and restart if needed."""
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
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(60)  # Wait a minute before trying again
