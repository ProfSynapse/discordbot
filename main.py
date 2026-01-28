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
from typing import Callable, Optional
from api_client import api_client
from config import config
from scraper.content_scheduler import ContentScheduler
from openai import OpenAI
from scraper.content_scraper import scrape_article_content
from functools import wraps
from image_generator import ImageGenerator
from session_manager import SessionManager

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
        self.session_manager: Optional[SessionManager] = None
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
        """Initialize bot commands, session manager, and scheduler."""
        logger.info("Starting bot setup...")
        try:
            # Initialize session manager
            self.session_manager = SessionManager(config.SESSION_DB_PATH, api_client)
            await self.session_manager.initialize()
            logger.info("Session manager initialized")

            # Sync command tree
            await self.tree.sync()
            logger.info("Command tree synced")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)

    async def on_ready(self):
        """Handle bot ready event and initialize scheduler."""
        try:
            logger.info(f'Bot is ready. Logged in as {self.user.name}')

            # Cleanup old sessions if configured
            if self.session_manager:
                if config.SESSION_MAX_AGE_DAYS > 0:
                    logger.info(f"Running session cleanup (max age: {config.SESSION_MAX_AGE_DAYS} days)")
                    removed = await self.session_manager.cleanup_old_sessions(config.SESSION_MAX_AGE_DAYS)
                    if removed > 0:
                        logger.info(f"Cleaned up {removed} old session(s)")
                else:
                    logger.info("Session auto-cleanup disabled (SESSION_MAX_AGE_DAYS=0)")

                # Log session statistics
                count = await self.session_manager.get_session_count()
                logger.info(f"Active sessions: {count}")

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
                # Get or create persistent session for this user
                user_id = str(interaction.user.id)
                session_uuid = await self.session_manager.get_or_create_session(user_id)

                # Optionally build context from OTHER users' recent messages
                context = ""
                if config.USE_CHANNEL_CONTEXT:
                    context = await self._build_channel_context(interaction.channel, interaction.user)

                # Get response (session maintains user's conversation history)
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

    async def _build_channel_context(
        self,
        channel: discord.TextChannel,
        exclude_user: discord.User,
        limit: int = None
    ) -> str:
        """Build context from recent channel messages, excluding the current user."""
        if limit is None:
            limit = config.CHANNEL_CONTEXT_LIMIT

        context = []
        async for msg in channel.history(limit=limit * 2):  # Get more to filter
            # Skip messages from the current user (their history is in their session)
            # Skip bot commands
            # Skip empty messages
            if (msg.author.id != exclude_user.id and
                not msg.content.startswith('/') and
                msg.content.strip()):
                context.append(f"{msg.author.display_name}: {msg.content}")

                if len(context) >= limit:
                    break

        # Reverse to chronological order (oldest first)
        context.reverse()

        if context:
            return "Recent channel context:\n" + "\n".join(context)
        return ""

    @with_error_handling
    async def generate_image(self, interaction: discord.Interaction, prompt: str):
        """Generate an image using Google's Nano Banana model."""
        await interaction.response.defer()

        # Send initial thinking message
        await interaction.followup.send("🎨 *Consulting the AI art masters...*")

        try:
            # Parse flags and get configuration
            clean_prompt, config = self.image_generator.parse_flags(prompt)

            # Generate the image
            content_type, image_data = await self.image_generator.generate_image(clean_prompt, config)

            # Create Discord file from image data (Nano Banana always returns PNG)
            file = discord.File(
                fp=io.BytesIO(image_data),
                filename="image.png"
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
    description="Generate an image using Google's Nano Banana model"
)
@commands.cooldown(1, 60, commands.BucketType.user)
@app_commands.describe(
    prompt=(
        "What would you like me to draw?\n"
        "Aspect: --square (default), --wide (16:9), --tall (9:16), "
        "--portrait (3:4), --landscape (4:3), --ultrawide (21:9)\n"
        "Resolution: --1k (default), --2k, --4k"
    )
)
async def image_command(interaction: discord.Interaction, prompt: str):
    """Command handler for /image"""
    await bot.generate_image(interaction, prompt)

@bot.tree.command(name="reset", description="Reset your conversation history with Professor Synapse")
async def reset_command(interaction: discord.Interaction):
    """Reset user's conversation history."""
    await interaction.response.defer(ephemeral=True)

    try:
        user_id = str(interaction.user.id)
        new_session_uuid = await bot.session_manager.reset_session(user_id)

        await interaction.followup.send(
            "🔄 **Your conversation has been reset!**\n"
            "Starting fresh with a new session.",
            ephemeral=True
        )
        logger.info(f"User {interaction.user.name} ({user_id}) reset their session")

    except Exception as e:
        logger.error(f"Error resetting session: {e}", exc_info=True)
        await interaction.followup.send(
            "❌ Failed to reset conversation history. Please try again later.",
            ephemeral=True
        )

@bot.tree.command(name="sessioninfo", description="View your session statistics")
async def sessioninfo_command(interaction: discord.Interaction):
    """Show session information."""
    await interaction.response.defer(ephemeral=True)

    try:
        user_id = str(interaction.user.id)
        info = await bot.session_manager.get_session_info(user_id)

        if info:
            from datetime import datetime
            created = datetime.fromisoformat(info['created_at'])
            last_used = datetime.fromisoformat(info['last_used'])

            embed = discord.Embed(
                title="📊 Your Session Info",
                color=discord.Color.blue()
            )
            embed.add_field(name="Session ID", value=f"`{info['session_uuid'][:16]}...`", inline=False)
            embed.add_field(name="Created", value=f"<t:{int(created.timestamp())}:R>", inline=True)
            embed.add_field(name="Last Used", value=f"<t:{int(last_used.timestamp())}:R>", inline=True)
            embed.add_field(name="Messages", value=str(info['message_count']), inline=True)

            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send(
                "You don't have an active session yet. Send a message with `/prof` to start!",
                ephemeral=True
            )

    except Exception as e:
        logger.error(f"Error getting session info: {e}")
        await interaction.followup.send(
            "❌ Failed to retrieve session info.",
            ephemeral=True
        )

if __name__ == "__main__":
    try:
        bot.run(config.DISCORD_TOKEN)
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)
