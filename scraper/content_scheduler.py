import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .news_scraper import scrape_all_sites
from pytube import Channel
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
        
        # YouTube channels to monitor
        self.youtube_channels = [
            "https://www.youtube.com/@synapticlabs",
            "https://www.youtube.com/@aiexplained-official",
            "https://www.youtube.com/@OpenAI",
            "https://www.youtube.com/@Google_DeepMind",
            # Add more as needed
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
            if new_articles:
                random.shuffle(new_articles)
                self.articles_queue.extend(new_articles)
                logger.info(f"Added {len(new_articles)} news articles to queue")
            else:
                logger.warning("No news articles found")
            
            # Fetch YouTube videos
            logger.info("Fetching YouTube videos...")
            youtube_count = 0
            for channel_url in self.youtube_channels:
                try:
                    videos = await asyncio.to_thread(self._fetch_channel_videos, channel_url)
                    for video in videos[:5]:  # Check last 5 videos
                        if video.watch_url not in self.seen_videos:
                            self.articles_queue.append({
                                'type': 'youtube',
                                'title': video.title,
                                'url': video.watch_url,
                                'author': video.author,
                                'thumbnail_url': video.thumbnail_url,
                                'published': datetime.now().isoformat()  # Add timestamp for sorting
                            })
                            self.seen_videos.add(video.watch_url)
                            youtube_count += 1
                except Exception as e:
                    logger.error(f"Error fetching from YouTube channel {channel_url}: {e}")
                    continue
            
            logger.info(f"Added {youtube_count} YouTube videos to queue")
            
            # Sort all content by date
            try:
                self.articles_queue.sort(
                    key=lambda x: datetime.fromisoformat(x.get('published', datetime.now().isoformat())),
                    reverse=True
                )
                logger.info(f"Total items in queue after fetch: {len(self.articles_queue)}")
            except Exception as e:
                logger.error(f"Error sorting content queue: {e}")
                
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
            summary = article['summary'][:1000] + "..." if len(article['summary']) > 1000 else article['summary']
            embed.description = summary
        
        if 'image_url' in article and article['image_url']:
            embed.set_image(url=article['image_url'])
            
        source = article.get('source', 'Unknown source')
        date_str = article.get('published', 'Unknown date')
        embed.set_footer(text=f"Published {date_str} • {source}")
        
        return embed
