"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities.
Simplified version with removed redundant processing.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import io
from typing import Callable
from api_client import api_client
from config import config
from scraper.content_scheduler import ContentScheduler
from openai import OpenAI
from scraper.content_scraper import scrape_article_content
from functools import wraps
from image_generator import ImageGenerator, ImageSize

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

def with_error_handling(func: Callable) -> Callable:
    """Decorator to handle errors in async functions."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            raise
    return wrapper

class DiscordBot(commands.Bot):
    """Discord bot implementation with streamlined message handling."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)
        
        self.scheduler = None
        self.image_generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
        self.thinking_phrases = [
            "📜 *Consulting the ancient tomes...*",
            "🤔 *Pondering the mysteries of the universe...*",
            "🕸️ *Focusing my neural networks...*",
            "👵 *Channeling the wisdom of the AI elders...*",
            "✨ *Weaving threads of knowledge...*",
            "🔮 *Gazing into the crystal GPU...*",
            "📚 *Speed-reading the internet...*",
            "🤓 *Doing some quick quantum calculations...*"
        ]

    async def setup_hook(self):
        """Initialize bot commands and scheduler."""
        logger.info("Starting bot setup...")
        try:
            await self.tree.sync()
            logger.info("Command tree synced")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)

    async def on_ready(self):
        """Handle bot ready event and initialize scheduler."""
        try:
            logger.info(f'Bot is ready. Logged in as {self.user.name}')
            
            # Only initialize scheduler if content scheduling is configured
            if config.CONTENT_CHANNEL_ID and config.YOUTUBE_API_KEY:
                if not self.scheduler:
                    logger.info("Initializing content scheduler...")
                    self.scheduler = ContentScheduler(
                        self, 
                        config.CONTENT_CHANNEL_ID
                    )
                    await self.scheduler.start()
                    logger.info("Content scheduler started successfully")
            else:
                logger.info("Content scheduling disabled (missing CONTENT_CHANNEL_ID or YOUTUBE_API_KEY)")
                
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)

    async def close(self):
        """Cleanup resources on shutdown."""
        if self.scheduler:
            await self.scheduler.stop()
        await super().close()

    @with_error_handling
    async def prof(self, interaction: discord.Interaction, prompt: str):
        """Main chat command with simplified response handling."""
        await interaction.response.defer()
        
        # Send initial thinking message
        thinking_embed = self._create_embed(
            title="Thinking...",
            description=self.thinking_phrases[0],
            color=discord.Color.blue()
        )
        bot_message = await interaction.followup.send(embed=thinking_embed)
        
        try:
            # Get response from API
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                context = await self._build_context(interaction.channel)
                response = await client.get_response(session_uuid, prompt, context)
                
                # Create and send response embed
                embed = self._create_embed(
                    title="Response",
                    color=discord.Color.green()
                )
                embed.add_field(name="Question", value=prompt[:1024], inline=False)
                embed.add_field(name="Answer", value=response[:1024], inline=False)
                embed.set_footer(text=f"Asked by {interaction.user.display_name}")
                
                await bot_message.edit(embed=embed)
                
        except Exception as e:
            logger.error(f"Error in prof: {e}", exc_info=True)
            error_embed = self._create_embed(
                title="Error",
                description="An error occurred while processing your request.",
                color=discord.Color.red()
            )
            await bot_message.edit(embed=error_embed)

    @staticmethod
    def _create_embed(title: str = None, description: str = None, color: discord.Color = None) -> discord.Embed:
        """Create a Discord embed with the given parameters."""
        embed = discord.Embed(color=color or discord.Color.default())
        if title:
            embed.title = title
        if description:
            embed.description = description
        return embed

    async def _build_context(self, channel: discord.TextChannel, limit: int = 10) -> str:
        """Build context from recent channel messages."""
        context = []
        async for msg in channel.history(limit=limit):
            if not msg.content.startswith('/') and msg.content.strip():
                context.append(f"{msg.author.display_name}: {msg.content}")
        
        return "\n".join(context)

    @with_error_handling
    async def generate_image(self, interaction: discord.Interaction, prompt: str):
        """Generate an image using Google's Imagen 4."""
        await interaction.response.defer()
        
        # Send initial thinking message
        await interaction.followup.send("🎨 *Consulting the AI art masters...*")
        
        try:
            # Parse flags and get configuration
            clean_prompt, config = self.image_generator.parse_flags(prompt)
            
            # Generate the image
            content_type, image_data = await self.image_generator.generate_image(clean_prompt, config)
            
            # Create Discord file from image data
            file = discord.File(
                fp=io.BytesIO(image_data),
                filename=f"image.{config.format.value}"
            )
            
            # Send the result
            await interaction.followup.send(
                f"🎨 **A masterpiece commissioned by {interaction.user.display_name}:**\n"
                f"*{clean_prompt}*",
                file=file
            )
            
        except Exception as e:
            logger.error(f"Image generation error: {str(e)}")
            await interaction.followup.send(
                "🎨 *I apologize, but I encountered an issue creating your image.*"
            )

# Initialize bot and register commands
bot = DiscordBot()

@bot.tree.command(name="prof", description="Chat with Professor Synapse")
@commands.cooldown(1, 60, commands.BucketType.user)
async def prof_command(interaction: discord.Interaction, *, prompt: str):
    """Command handler for /prof"""
    await bot.prof(interaction, prompt=prompt)

@bot.tree.command(
    name="image", 
    description="Generate an image using Google's Imagen 4"
)
@commands.cooldown(1, 60, commands.BucketType.user)
@app_commands.describe(
    prompt=(
        "What would you like me to draw?\n"
        "Model: --fast (default, fixed size), --standard, --ultra\n"
        "Size (Standard/Ultra only): --square or --1k (1024x1024, default), --2k or --large (2048x2048)\n"
        "Format: --png (default), --jpeg"
    )
)
async def image_command(interaction: discord.Interaction, prompt: str):
    """Command handler for /image"""
    await bot.generate_image(interaction, prompt)

if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)
