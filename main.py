"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities 
with improved message formatting and error handling.
"""

import asyncio
import json
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

# Configure logging with DEBUG level
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
    """
    Decorator to handle errors in async functions.
    Logs errors and re-raises them for proper handling.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            raise
    return wrapper

class ImageSize(Enum):
    """
    Enum for supported image generation sizes with descriptions.
    """
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

class MessageFormatter:
    """
    Handles formatting of bot messages and responses.
    """
    @staticmethod
    def format_response(text: str) -> str:
        """Extract response from JSON with debug logging"""
        try:
            logger.debug("=== INPUT TEXT ===")
            logger.debug(text)
            
            # Parse JSON and get response text
            if text.strip().startswith('['):
                data = json.loads(text)
                for item in reversed(data):
                    if isinstance(item, dict) and 'response' in item:
                        response = item['response']
                        logger.debug("=== RAW RESPONSE ===")
                        logger.debug(repr(response))  # Use repr to see exact string
                        return response  # Return exactly as is
            
            elif text.strip().startswith('{'):
                data = json.loads(text)
                if isinstance(data, dict) and 'response' in data:
                    response = data['response']
                    logger.debug("=== RAW RESPONSE ===")
                    logger.debug(repr(response))  # Use repr to see exact string
                    return response  # Return exactly as is
            
            return text
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return text
        except Exception as e:
            logger.error(f"Error in format_response: {e}")
            return text

class DiscordBot(commands.Bot):
    """
    Discord bot implementation with improved message handling and error recovery.
    """
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)
        
        self.scheduler = None
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.message_formatter = MessageFormatter()
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
                try:
                    logger.info("Initializing content scheduler...")
                    self.scheduler = ContentScheduler(
                        self, 
                        config.NEWS_CHANNEL_ID,
                        config.YOUTUBE_CHANNEL_ID
                    )
                    await self.scheduler.start()
                    logger.info("Content scheduler started successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)

    async def close(self):
        """Cleanup resources on shutdown."""
        if self.scheduler:
            await self.scheduler.stop()
        await super().close()

    # In DiscordBot class
    async def prof(self, interaction: discord.Interaction, prompt: str):
        """Main chat command with detailed logging"""
        await interaction.response.defer()
        
        try:
            # Send initial thinking message
            bot_message = await interaction.followup.send(embed=self._create_initial_embed(interaction.user, prompt))
            
            # Get response
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                context = await self._build_context(interaction.channel)
                
                bot_response = await client.get_response(session_uuid, prompt, context)
                
                # Log exact response
                logger.debug("=== RESPONSE BEFORE FORMATTING ===")
                logger.debug(repr(bot_response))
                
                formatted_response = self.message_formatter.format_response(bot_response)
                
                # Log after formatting
                logger.debug("=== RESPONSE AFTER FORMATTING ===")
                logger.debug(repr(formatted_response))
                
                # Create embed with raw response
                embed = discord.Embed(color=discord.Color.green())
                embed.add_field(
                    name="Question",
                    value=prompt[:1024],
                    inline=False
                )
                
                # Log final response being set
                logger.debug("=== SETTING EMBED VALUE ===")
                logger.debug(repr(formatted_response[:1024]))
                
                embed.add_field(
                    name="Response",
                    value=formatted_response[:1024],
                    inline=False
                )
                
                await bot_message.edit(embed=embed)
                
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            # Error handling...
            error_embed = self._create_error_embed()
            if 'bot_message' in locals():
                await bot_message.edit(embed=error_embed)
            else:
                await interaction.followup.send(embed=error_embed)

    def _create_initial_embed(self, user: discord.User, prompt: str) -> discord.Embed:
        """Create the initial response embed with the question."""
        embed = discord.Embed(
            description=f"**Question:**\n{prompt}",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Asked by {user.display_name}")
        return embed

    def _create_final_embed(self, user: discord.User, prompt: str, response: str) -> discord.Embed:
        """Create the final response embed with both question and answer."""
        embed = discord.Embed(color=discord.Color.green())
        embed.add_field(
            name="Question",
            value=prompt[:1024] if len(prompt) > 1024 else prompt,
            inline=False
        )
        embed.add_field(
            name="Response",
            value=response[:1024] if len(response) > 1024 else response,
            inline=False
        )
        embed.set_footer(text=f"Asked by {user.display_name}")
        return embed

    def _create_error_embed(self) -> discord.Embed:
        """Create an error embed for failed requests."""
        return discord.Embed(
            title="❌ Error",
            description="An error occurred while processing your request. I'll try to fix this and be back shortly!",
            color=discord.Color.red()
        )

    async def _animate_thinking(self, message: discord.Message, embed: discord.Embed, prompt: str):
        """Animate the thinking state with rotating phrases."""
        for phrase in self.thinking_phrases:
            embed.description = f"**Question:**\n{prompt}\n\n{phrase}"
            await message.edit(embed=embed)
            await asyncio.sleep(1.5)

    async def _build_context(self, channel: discord.TextChannel) -> str:
        """Build context from recent channel messages."""
        context = "<recent_channel_conversation>\n"
        message_count = 0
        
        async for msg in channel.history(limit=10):
            if not msg.content.startswith('/') and msg.content.strip():
                context += f"{msg.author.display_name}: {msg.content}\n"
                message_count += 1
                
        context += "</recent_channel_conversation>"
        logger.info(f"Built context with {message_count} messages")
        return context

    async def generate_image(self, interaction: discord.Interaction, prompt: str, size: ImageSize = ImageSize.SQUARE):
        """Generate an image using DALL-E with improved error handling."""
        await interaction.response.defer()
        await interaction.followup.send("🎨 *Professor Synapse grabs his digital paintbrush and canvas...*")
        
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
                f"🎨 **A masterpiece commissioned by {interaction.user.display_name}:**\n" +
                f"*{prompt}*\n\n" +
                f"[View Image]({image_url})"
            )
            
        except Exception as e:
            logging.error(f"Image generation error: {str(e)}")
            await interaction.followup.send(
                "🎨 *Alas, my artistic vision has failed me. Perhaps we should try a different subject?*"
            )

# Initialize bot and register commands
bot = DiscordBot()

@bot.tree.command(name="prof", description="Chat with Professor Synapse")
@commands.cooldown(1, 60, commands.BucketType.user)
async def prof_command(interaction: discord.Interaction, *, prompt: str):
    await bot.prof(interaction, prompt=prompt)

@bot.tree.command(
    name="image", 
    description="Generate an image using DALL-E (add --square, --portrait, or --wide to change format)"
)
@commands.cooldown(1, 60, commands.BucketType.user)
@app_commands.describe(
    prompt="What would you like me to draw? (add --square, --portrait, or --wide at the end)"
)

async def image_command(
    interaction: discord.Interaction, 
    prompt: str
):
    """Generate an image using DALL-E 3"""
    # Parse size from flags in prompt
    size_map = {
        "--square": ImageSize.SQUARE,
        "--portrait": ImageSize.PORTRAIT,
        "--wide": ImageSize.LANDSCAPE,
        "--landscape": ImageSize.LANDSCAPE  # Alternative flag
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
    # Install discord package if not present
    try:
        bot.run(config.DISCORD_TOKEN)
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)
