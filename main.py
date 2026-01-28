"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities.
Simplified version with removed redundant processing.
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Callable
from api_client import api_client
from config import config
from scraper.content_scheduler import ContentScheduler
from openai import OpenAI
from enum import Enum
from scraper.content_scraper import scrape_article_content
from functools import wraps

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

class ImageSize(Enum):
    """Enum for supported image generation sizes."""
    SQUARE = "1024x1024"
    PORTRAIT = "1024x1792"
    LANDSCAPE = "1792x1024"
    
    @classmethod
    def get_description(cls, size: str) -> str:
        descriptions = {
            "square": "Perfect square (1024x1024)",
            "portrait": "Vertical/portrait (1024x1792)",
            "landscape": "Horizontal/landscape (1792x1024)"
        }
        return descriptions.get(size.lower(), "Unknown size")

class DiscordBot(commands.Bot):
    """Discord bot implementation with streamlined message handling."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)
        
        self.scheduler = None
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
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
            
            if not self.scheduler:
                logger.info("Initializing content scheduler...")
                self.scheduler = ContentScheduler(
                    self, 
                    config.NEWS_CHANNEL_ID,
                    config.YOUTUBE_CHANNEL_ID
                )
                await self.scheduler.start()
                logger.info("Content scheduler started successfully")
                
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
                # Use embed description (4096 char max) for the answer instead of
                # a field (1024 char max) to avoid silent truncation of long responses.
                truncated_response = self._truncate_response(response, max_length=4096)
                embed = self._create_embed(
                    title="Response",
                    description=truncated_response,
                    color=discord.Color.green()
                )
                embed.add_field(name="Question", value=prompt[:1024], inline=False)
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

    @staticmethod
    def _truncate_response(text: str, max_length: int = 4096) -> str:
        """Truncate a response to fit within Discord's embed description limit.

        Attempts to break at the last sentence boundary before the limit.
        Falls back to a hard truncation with an ellipsis indicator if no
        sentence boundary is found.

        Args:
            text: The full response text.
            max_length: Maximum allowed characters (default 4096 for embed description).

        Returns:
            The original text if within limits, or a truncated version with '...' appended.
        """
        if len(text) <= max_length:
            return text

        # Reserve space for the truncation indicator
        truncation_indicator = "..."
        limit = max_length - len(truncation_indicator)
        truncated = text[:limit]

        # Try to break at the last sentence-ending punctuation (. ! ?)
        last_sentence_end = max(
            truncated.rfind('. '),
            truncated.rfind('! '),
            truncated.rfind('? '),
            truncated.rfind('.\n'),
            truncated.rfind('!\n'),
            truncated.rfind('?\n'),
        )

        if last_sentence_end > limit // 2:
            # Found a reasonable sentence boundary in the latter half of the text
            truncated = truncated[:last_sentence_end + 1]

        return truncated + truncation_indicator

    async def _build_context(self, channel: discord.TextChannel, limit: int = 10) -> str:
        """Build context from recent channel messages."""
        context = []
        async for msg in channel.history(limit=limit):
            if not msg.content.startswith('/') and msg.content.strip():
                context.append(f"{msg.author.display_name}: {msg.content}")
        
        return "\n".join(context)

    @with_error_handling
    async def generate_image(self, interaction: discord.Interaction, prompt: str, size: ImageSize = ImageSize.SQUARE):
        """Generate an image using DALL-E with error handling."""
        await interaction.response.defer()
        await interaction.followup.send("🎨 *Preparing to create your masterpiece...*")
        
        try:
            response = self.openai_client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size.value,
                quality="standard",
                n=1,
            )
            
            image_url = response.data[0].url
            await interaction.followup.send(
                f"🎨 **A masterpiece commissioned by {interaction.user.display_name}:**\n"
                f"*{prompt}*\n\n"
                f"[View Image]({image_url})"
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
    description="Generate an image using DALL-E"
)
@commands.cooldown(1, 60, commands.BucketType.user)
@app_commands.describe(
    prompt="What would you like me to draw? (add --square, --portrait, or --wide at the end)"
)
async def image_command(interaction: discord.Interaction, prompt: str):
    """Command handler for /image"""
    # Parse size from flags in prompt
    size_map = {
        "--square": ImageSize.SQUARE,
        "--portrait": ImageSize.PORTRAIT,
        "--wide": ImageSize.LANDSCAPE,
        "--landscape": ImageSize.LANDSCAPE
    }
    
    # Default to square if no flag found
    image_size = ImageSize.SQUARE
    clean_prompt = prompt
    
    # Check for size flags and remove from prompt
    for flag, size in size_map.items():
        if flag in prompt.lower():
            image_size = size
            clean_prompt = prompt.lower().replace(flag, "").strip()
            break
    
    await bot.generate_image(interaction, clean_prompt, image_size)

if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)