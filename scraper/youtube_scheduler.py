import asyncio
import logging
from datetime import datetime, timedelta
import discord
from pytube import Channel
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class YouTubeScheduler:
    def __init__(self, bot, channel_id: int):
        self.bot = bot
        self.channel_id = channel_id
        self.running = False
        self._schedule_task = None
        self.seen_videos = set()
        
        # List of YouTube channels to monitor (usernames or channel URLs)
        self.youtube_channels = [
            "https://www.youtube.com/@synapticlabs",
            "https://www.youtube.com/@godago",
            "https://www.youtube.com/@aiexplained-official",
            "https://www.youtube.com/@WesRoth",
            "https://www.youtube.com/@AIJasonZ",
            "https://www.youtube.com/@OpenAI",
            "https://www.youtube.com/@anthropic-ai",
            "https://www.youtube.com/@Google",
            "https://www.youtube.com/@Google_DeepMind",
            "https://www.youtube.com/@GroqInc",
            "https://www.youtube.com/@TheVerge"
            # Add more channels as needed
        ]

    async def start(self):
        """Start the YouTube monitoring loop"""
        try:
            logger.info("Starting YouTubeScheduler")
            
            # Verify Discord channel access
            self.discord_channel = self.bot.get_channel(self.channel_id)
            if not self.discord_channel:
                raise ValueError(f"Discord channel {self.channel_id} not found")
            
            self.running = True
            
            # Start monitoring task
            self._schedule_task = asyncio.create_task(self._monitor_youtube())
            logger.info("YouTube scheduler started successfully")
            
        except Exception as e:
            logger.error(f"Error starting YouTube scheduler: {e}", exc_info=True)
            self.running = False
            raise

    async def stop(self):
        """Stop the monitoring loop"""
        logger.info("Stopping YouTube scheduler...")
        self.running = False
        if self._schedule_task:
            self._schedule_task.cancel()

    async def _monitor_youtube(self):
        """Monitor YouTube channels for new videos"""
        while self.running:
            try:
                for channel_url in self.youtube_channels:
                    # Run in thread pool to avoid blocking
                    videos = await asyncio.to_thread(self._fetch_channel_videos, channel_url)
                    
                    for video in videos[:5]:  # Check last 5 videos
                        if video.watch_url not in self.seen_videos:
                            self.seen_videos.add(video.watch_url)
                            
                            # Create embed
                            embed = discord.Embed(
                                title=video.title,
                                url=video.watch_url,
                                description=f"New video from {video.author}!",
                                color=discord.Color.red()
                            )
                            
                            if video.thumbnail_url:
                                embed.set_image(url=video.thumbnail_url)
                                
                            await self.discord_channel.send(embed=embed)
                            logger.info(f"Posted new video: {video.title}")
                            
                            # Wait a bit before next video
                            await asyncio.sleep(random.randint(10, 30))
                
                # Wait between checks (4-6 hours)
                await asyncio.sleep(random.randint(14400, 21600))
                
            except Exception as e:
                logger.error(f"Error in YouTube monitor: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error

    def _fetch_channel_videos(self, channel_url: str):
        """Fetch videos from a YouTube channel"""
        try:
            channel = Channel(channel_url)
            return list(channel.videos)
        except Exception as e:
            logger.error(f"Error fetching videos from {channel_url}: {e}")
            return []
