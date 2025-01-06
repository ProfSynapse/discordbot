import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .news_scraper import scrape_all_sites
import discord
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ArticleScheduler:
    def __init__(self, bot, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id
        self.articles_queue: List[Dict[str, Any]] = []
        self.running = False
        self._schedule_task = None
        self._drip_task = None
        
        logger.info(f"Initializing ArticleScheduler with channel ID: {channel_id}")
        self.channel = self.bot.get_channel(channel_id)
        if not self.channel:
            logger.error(f"Could not find channel {channel_id}")
            raise ValueError(f"Channel {channel_id} not found")
        logger.info(f"Found channel: #{self.channel.name}")

    async def start(self):
        """Start the scheduling loop"""
        try:
            logger.info("Starting ArticleScheduler")
            self.running = True
            
            # Immediate first scrape
            logger.info("Performing initial scrape...")
            await self._perform_scrape()
            logger.info("Initial scrape completed")
            
            # Start background tasks
            logger.info("Starting scheduler tasks")
            self._schedule_task = asyncio.create_task(self._schedule_scrapes(), name="schedule_scrapes")
            self._drip_task = asyncio.create_task(self._drip_articles(), name="drip_articles")
            
            # Monitor tasks for errors
            asyncio.create_task(self._monitor_tasks())
            logger.info("Scheduler tasks started")
            
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
                if self._schedule_task and self._schedule_task.done():
                    if self._schedule_task.exception():
                        logger.error(f"Schedule task failed: {self._schedule_task.exception()}")
                        self._schedule_task = asyncio.create_task(self._schedule_scrapes())
                
                if self._drip_task and self._drip_task.done():
                    if self._drip_task.exception():
                        logger.error(f"Drip task failed: {self._drip_task.exception()}")
                        self._drip_task = asyncio.create_task(self._drip_articles())
                
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in task monitor: {e}")
                await asyncio.sleep(60)

    async def _schedule_scrapes(self):
        """Run scrapes twice daily"""
        while self.running:
            now = datetime.now()
            # Schedule for 6AM and 6PM
            next_run = now.replace(hour=18 if now.hour >= 6 and now.hour < 18 else 6, 
                                 minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
            await asyncio.sleep((next_run - now).seconds)
            if self.running:
                await self._perform_scrape()

    async def _perform_scrape(self):
        """Scrape articles and add them to queue"""
        try:
            logger.info("Starting article scrape")
            new_articles = await scrape_all_sites()
            logger.info(f"Scraped {len(new_articles)} new articles")
            
            if not new_articles:
                logger.warning("No articles found during scrape")
                return
                
            random.shuffle(new_articles)
            self.articles_queue.extend(new_articles)
            logger.info(f"Added {len(new_articles)} articles to queue")
        except Exception as e:
            logger.error(f"Error during scrape: {e}", exc_info=True)

    async def _drip_articles(self):
        """Release articles from queue throughout the day"""
        while self.running:
            try:
                if self.articles_queue:
                    article = self.articles_queue.pop(0)
                    # Refresh channel reference
                    self.channel = self.bot.get_channel(self.channel_id)
                    if self.channel:
                        # Create embed for better formatting
                        embed = discord.Embed(
                            title=article['title'],
                            url=article['url'],
                            description=article['summary'],
                            color=discord.Color.blue()
                        )
                        
                        # Format the published date
                        pub_date = datetime.fromisoformat(article['published'])
                        embed.set_footer(text=f"Published {pub_date.strftime('%Y-%m-%d %H:%M')} • {article['source']}")
                        
                        logger.info(f"Posting article: {article['title']}")
                        await self.channel.send(embed=embed)
                    else:
                        logger.error(f"Could not find channel with ID {self.channel_id}, skipping article")
                        continue

                    # Random delay between 30-90 minutes before next article
                    delay = random.randint(1800, 5400)
                    logger.info(f"Waiting {delay} seconds before next article")
                    await asyncio.sleep(delay)
                else:
                    logger.info("Article queue empty, waiting 15 minutes")
                    await asyncio.sleep(900)
            except Exception as e:
                logger.error(f"Error in _drip_articles: {e}", exc_info=True)
                await asyncio.sleep(900)  # Wait 15 minutes on error
