import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from .news_scraper import scrape_all_sites

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ArticleScheduler:
    def __init__(self, bot, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id
        self.articles_queue: List[Dict[str, Any]] = []
        self.running = False
    
    async def start(self):
        """Start the scheduling loop"""
        self.running = True
        asyncio.create_task(self._schedule_scrapes())
        asyncio.create_task(self._drip_articles())
    
    async def stop(self):
        """Stop the scheduling loop"""
        self.running = False

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
        """Scrape articles and add them to queue in random chunks"""
        try:
            new_articles = await scrape_all_sites()
            random.shuffle(new_articles)
            
            while new_articles:
                chunk_size = random.randint(2, 3)
                chunk = new_articles[:chunk_size]
                new_articles = new_articles[chunk_size:]
                self.articles_queue.extend(chunk)
                
            logger.info(f"Added {len(self.articles_queue)} articles to queue")
        except Exception as e:
            logger.error(f"Error during scrape: {e}")

    async def _drip_articles(self):
        """Release articles from queue throughout the day"""
        while self.running:
            if self.articles_queue:
                article = self.articles_queue.pop(0)
                channel = self.bot.get_channel(self.channel_id)
                if channel:
                    await channel.send(
                        f"📰 **New AI Article from {article['source']}**\n\n"
                        f"**{article['title']}**\n\n"
                        f"{article['summary']}\n\n"
                        f"🔗 {article['url']}"
                    )
                # Random delay between 30-90 minutes before next article
                delay = random.randint(1800, 5400)
                await asyncio.sleep(delay)
            else:
                # If queue is empty, check again in 15 minutes
                await asyncio.sleep(900)
