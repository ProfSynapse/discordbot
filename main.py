"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities 
with improved message formatting and error handling.
"""

import asyncio
import re
import json
import discord
from discord.ext import commands
from discord import app_commands
import textwrap
import logging
from typing import List, Dict, Any, Optional, Callable
from api_client import api_client, APIResponseError
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
        """
        Format API response while preserving Discord markdown and formatting.
        Handles both JSON and plain text responses.
        """
        logger.debug("=== Raw Input ===")
        logger.debug(text)
        
        try:
            # Extract response from JSON if necessary
            text = MessageFormatter._extract_response_from_json(text)
            
            # Split into lines and clean while preserving formatting
            lines = text.split('\n')
            
            # Remove empty lines at start/end
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and not lines[-1].strip():
                lines.pop()
                
            # Clean each line while preserving markdown
            cleaned_lines = []
            for line in lines:
                # Preserve markdown indicators at start of lines
                if re.match(r'[\*\_\~\`\>\#]', line.lstrip()):
                    cleaned_lines.append(line.rstrip())
                else:
                    cleaned_lines.append(line.strip())
            
            # Rejoin with proper newlines
            text = '\n'.join(cleaned_lines)
            
            # Clean up any remaining formatting issues
            text = MessageFormatter._clean_formatting(text)
            
            logger.debug("=== Formatted Output ===")
            logger.debug(text)
            
            return text
            
        except Exception as e:
            logger.error(f"Error formatting response: {e}")
            return text.strip()

    @staticmethod
    def _extract_response_from_json(text: str) -> str:
        """
        Extract response field from JSON data if present.
        """
        if text.strip().startswith('['):
            data = json.loads(text)
            for item in reversed(data):
                if isinstance(item, dict) and item.get('response'):
                    return item['response']
        elif text.strip().startswith('{'):
            data = json.loads(text)
            if isinstance(data, dict):
                return data.get('response', text)
        return text

    @staticmethod
    def _clean_formatting(text: str) -> str:
        """
        Clean up text formatting while preserving markdown syntax.
        """
        # Remove trailing spaces/tabs from lines
        text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
        
        # Clean up multiple consecutive empty lines
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Preserve markdown formatting
        text = re.sub(r'^\s+(?=[\*\_\~\`\>\#])', '', text, flags=re.MULTILINE)
        
        return text.strip()

    @staticmethod
    def chunk_message(text: str, max_length: int = 2000) -> List[str]:
        """
        Split long messages into chunks while preserving formatting.
        """
        if len(text) <= max_length:
            return [text]
            
        chunks = []
        current_chunk = []
        current_length = 0
        
        # Split by lines to preserve formatting
        lines = text.split('\n')
        
        for line in lines:
            if len(line) > max_length:
                # Handle long lines by splitting on spaces
                words = line.split(' ')
                current_line = []
                
                for word in words:
                    if current_length + len(' '.join(current_line)) + len(word) + 1 <= max_length:
                        current_line.append(word)
                    else:
                        if current_line:
                            current_chunk.append(' '.join(current_line))
                            current_length += len(current_chunk[-1]) + 1
                        if current_length > 0:
                            chunks.append('\n'.join(current_chunk))
                            current_chunk = []
                            current_length = 0
                        current_line = [word]
                
                if current_line:
                    current_chunk.append(' '.join(current_line))
                    current_length += len(current_chunk[-1]) + 1
                    
            elif current_length + len(line) + 1 <= max_length:
                current_chunk.append(line)
                current_length += len(line) + 1
            else:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_length = len(line) + 1
        
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        # Add part numbers for multiple chunks
        if len(chunks) > 1:
            return [f"Part {i+1}/{len(chunks)}:\n{chunk}" for i, chunk in enumerate(chunks)]
        return chunks

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

    async def prof(self, interaction: discord.Interaction, *, prompt: str):
        """
        Main chat command implementation with improved response formatting.
        """
        await interaction.response.defer()
        
        try:
            # Initialize response embed
            response_embed = self._create_initial_embed(interaction.user, prompt)
            bot_message = await interaction.followup.send(embed=response_embed)
            
            # Animate thinking state
            await self._animate_thinking(bot_message, response_embed, prompt)
            
            # Build conversation context
            context = await self._build_context(interaction.channel)
            
            # Get AI response
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                logger.info(f"Created session: {session_uuid}")
                
                bot_response = await client.get_response(session_uuid, prompt, context)
                logger.info("=== Raw AI Response ===")
                logger.info(bot_response)
                
            if not bot_response or bot_response.isspace():
                raise APIResponseError("Empty response received from API")

            # Format and send final response
            formatted_response = self.message_formatter.format_response(bot_response)
            final_embed = self._create_final_embed(interaction.user, prompt, formatted_response)
            await bot_message.edit(embed=final_embed)

        except Exception as e:
            logger.error(f"Error in prof command: {e}", exc_info=True)
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
            value=prompt,
            inline=False
        )
        embed.add_field(
            name="Response",
            value=response,
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
