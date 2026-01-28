"""
Location: /mnt/f/Code/discordbot/main.py
Summary: Main Discord bot module that handles all Discord-specific functionality.
         This bot integrates with GPT Trainer API to provide conversational AI capabilities.
         Defines the DiscordBot class (commands.Bot subclass), registers slash commands
         (/prof, /image, /reset, /sessioninfo), and provides the main() entry point.

Used by: Executed directly as the application entry point.
Uses: api_client.py (API calls), config.py (settings), session_manager.py (session
      persistence), image_generator.py (image generation), scraper/ (content scheduling),
      health_check.py (HTTP health endpoint for Docker/Railway).
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
import io
import random
import re
from typing import Callable, List, Optional
from api_client import api_client
from config import config
from scraper.content_scheduler import ContentScheduler
from functools import wraps
from image_generator import ImageGenerator
from session_manager import SessionManager
from health_check import HealthCheckServer

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

# Maximum number of characters allowed in command prompts sent to external APIs.
MAX_PROMPT_LENGTH = 2000

# Maximum total characters for channel context built from recent messages.
MAX_CONTEXT_CHARS = 2000


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
        self.health_server: Optional[HealthCheckServer] = None
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
        """Initialize bot commands, session manager, and scheduler.

        Session manager initialization is critical -- if it fails the bot cannot
        function correctly, so the exception is re-raised after logging.  Command
        tree sync is best-effort and a failure is logged but not fatal.
        """
        logger.info("Starting bot setup...")

        # Initialize session manager (critical -- re-raise on failure)
        try:
            self.session_manager = SessionManager(config.SESSION_DB_PATH, api_client)
            await self.session_manager.initialize()
            logger.info("Session manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize session manager: {e}", exc_info=True)
            raise

        # Sync command tree (non-fatal)
        try:
            await self.tree.sync()
            logger.info("Command tree synced")
        except Exception as e:
            logger.error(f"Failed to sync command tree: {e}", exc_info=True)

    async def on_ready(self):
        """Handle bot ready event, start health check server, and initialize scheduler."""
        try:
            logger.info(f'Bot is ready. Logged in as {self.user.name}')

            # Start health check HTTP server (non-fatal -- bot works without it)
            if not self.health_server:
                try:
                    self.health_server = HealthCheckServer(self)
                    await self.health_server.start()
                except Exception as e:
                    logger.error(f"Failed to start health check server: {e}", exc_info=True)
                    self.health_server = None

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
        if self.health_server:
            await self.health_server.stop()
        if self.scheduler:
            await self.scheduler.stop()
        # Explicitly close the shared API client session
        await api_client.close()
        await super().close()

    async def on_message(self, message: discord.Message):
        """Handle @mention messages for natural conversation.

        When a user @mentions the bot, this handler strips the mention text,
        retrieves or creates a session for the user, calls the GPT Trainer API,
        and replies with plain text. This creates a conversational reply chain
        in Discord that feels like talking to a person rather than submitting a
        form.

        No cooldown is applied here by design -- natural conversation should
        not be rate-limited. Be aware this means API costs scale with mention
        frequency; monitor usage in production.
        """
        # Ignore messages from bots (including self) to prevent loops
        if message.author.bot:
            return

        # Check if the bot was mentioned in this message
        if self.user and self.user.mentioned_in(message):
            # Strip the bot's mention(s) from the message to get the clean prompt.
            # Discord mentions appear as <@USER_ID> or <@!USER_ID> (nickname form).
            clean_content = message.content
            for mention_pattern in [f'<@{self.user.id}>', f'<@!{self.user.id}>']:
                clean_content = clean_content.replace(mention_pattern, '')
            clean_content = clean_content.strip()

            # Ignore empty messages (someone just typed "@bot" with nothing else)
            if not clean_content:
                await message.reply("Hey! What's on your mind?")
                await self.process_commands(message)
                return

            # Validate prompt length before sending to external API
            if len(clean_content) > MAX_PROMPT_LENGTH:
                await message.reply(
                    f"That message is a bit too long ({len(clean_content)} characters). "
                    f"Could you keep it under {MAX_PROMPT_LENGTH} characters?"
                )
                await self.process_commands(message)
                return

            # Show typing indicator while processing -- makes it feel like
            # someone is actually typing a reply
            async with message.channel.typing():
                try:
                    async with api_client as client:
                        # Get or create persistent session for this user
                        user_id = str(message.author.id)
                        session_uuid = await self.session_manager.get_or_create_session(user_id)

                        # Optionally build context from OTHER users' recent messages
                        context = ""
                        if config.USE_CHANNEL_CONTEXT:
                            context = await self._build_channel_context(
                                message.channel, message.author
                            )

                        # Get response (session maintains user's conversation history)
                        response = await client.get_response(
                            session_uuid, clean_content, context
                        )

                        # Split into Discord-safe chunks and send as replies
                        chunks = self._split_response(response)

                        # First chunk is a direct reply to the user's message,
                        # creating a visible reply chain in Discord
                        await message.reply(chunks[0])

                        # Subsequent chunks are sent as plain channel messages to
                        # avoid stacking multiple reply indicators
                        for chunk in chunks[1:]:
                            await message.channel.send(chunk)

                except Exception as e:
                    logger.error(
                        f"Error handling mention from {message.author}: {e}",
                        exc_info=True
                    )
                    await message.reply(
                        "Sorry, I ran into an issue processing that. Please try again."
                    )

        # IMPORTANT: Always call process_commands so slash commands and prefix
        # commands continue to work alongside the @mention handler.
        await self.process_commands(message)

    @with_error_handling
    async def prof(self, interaction: discord.Interaction, prompt: str):
        """Main chat command that responds with plain conversational text."""
        await interaction.response.defer()

        # Send initial thinking message as plain italic text
        thinking_msg = random.choice(self.thinking_phrases)
        bot_message = await interaction.followup.send(thinking_msg)

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

                # Split the response into Discord-safe chunks and send as plain text
                chunks = self._split_response(response)

                # Edit the thinking message with the first chunk
                await bot_message.edit(content=chunks[0])

                # Send any remaining chunks as followup messages
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)

        except Exception as e:
            logger.error(f"Error in prof: {e}", exc_info=True)
            await bot_message.edit(
                content="Sorry, I ran into an issue processing that. Please try again."
            )

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
    def _split_response(text: str, max_length: int = 2000) -> List[str]:
        """Split a response into chunks that fit within Discord's message limit.

        Splits intelligently at natural text boundaries, trying in order:
        1. Double newlines (paragraph boundaries)
        2. Single newlines
        3. Sentence boundaries ('. ', '! ', '? ')
        4. Hard split at max_length with '...' continuation marker

        Preserves markdown code blocks by avoiding splits inside them when
        possible.

        Args:
            text: The full response text to split.
            max_length: Maximum characters per chunk (default 2000, Discord's limit).

        Returns:
            List of strings, each within max_length.
        """
        if not text:
            return [""]

        if len(text) <= max_length:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break

            # Find the best split point within max_length
            candidate = remaining[:max_length]

            # Avoid splitting inside a code block. Find all code block fences
            # (```) in the candidate and check if we're inside an open block.
            fence_positions = [m.start() for m in re.finditer(r'```', candidate)]
            inside_code_block = len(fence_positions) % 2 == 1  # odd = unclosed

            if inside_code_block:
                # Try to split before the last opening fence so the code block
                # stays intact in the next chunk.
                last_fence = fence_positions[-1]
                if last_fence > max_length // 4:
                    # Only use this if the fence is reasonably far into the text
                    # to avoid tiny chunks.
                    candidate = remaining[:last_fence]

            split_point = len(candidate)

            # Strategy 1: Split on double newline (paragraph boundary)
            para_break = candidate.rfind('\n\n')
            if para_break > max_length // 4:
                split_point = para_break + 2  # include the double newline
            else:
                # Strategy 2: Split on single newline
                line_break = candidate.rfind('\n')
                if line_break > max_length // 4:
                    split_point = line_break + 1
                else:
                    # Strategy 3: Split on sentence boundary
                    sentence_end = max(
                        candidate.rfind('. '),
                        candidate.rfind('! '),
                        candidate.rfind('? '),
                    )
                    if sentence_end > max_length // 4:
                        split_point = sentence_end + 2  # include the punctuation and space
                    else:
                        # Strategy 4: Hard split with continuation marker
                        split_point = max_length - 3  # room for '...'
                        chunks.append(remaining[:split_point] + '...')
                        remaining = remaining[split_point:]
                        continue

            chunks.append(remaining[:split_point].rstrip())
            remaining = remaining[split_point:].lstrip('\n')

        return chunks if chunks else [""]

    @staticmethod
    def _truncate_response(text: str, max_length: int = 2000) -> str:
        """Truncate a response to fit within Discord's message limit.

        This is a safety net for cases where splitting is not appropriate
        (e.g., embed descriptions). Attempts to break at the last sentence
        boundary before the limit. Falls back to a hard truncation with an
        ellipsis indicator if no sentence boundary is found.

        Args:
            text: The full response text.
            max_length: Maximum allowed characters (default 2000 for plain messages).

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
        """Build context from recent channel messages, excluding the current user.

        Applies MAX_CONTEXT_CHARS to prevent unbounded context growth. When the
        total accumulated text exceeds the limit, the oldest collected messages
        are dropped first.
        """
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

        if not context:
            return ""

        # Enforce maximum context size by removing oldest messages first
        joined = "\n".join(context)
        while len(joined) > MAX_CONTEXT_CHARS and len(context) > 1:
            context.pop(0)  # drop oldest message
            joined = "\n".join(context)

        # Final guard: if a single message still exceeds the limit, hard-truncate
        if len(joined) > MAX_CONTEXT_CHARS:
            joined = joined[:MAX_CONTEXT_CHARS]

        return "Recent channel context:\n" + joined

    @with_error_handling
    async def generate_image(self, interaction: discord.Interaction, prompt: str):
        """Generate an image using Google's Nano Banana model."""
        await interaction.response.defer()

        # Send initial thinking message
        await interaction.followup.send("🎨 *Consulting the AI art masters...*")

        try:
            # Parse flags and get configuration
            # Variable named img_config to avoid shadowing the module-level `config` import
            clean_prompt, img_config = self.image_generator.parse_flags(prompt)

            # Generate the image
            content_type, image_data = await self.image_generator.generate_image(clean_prompt, img_config)

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


def _register_commands(bot: DiscordBot) -> None:
    """Register all slash commands on the bot's command tree.

    Separated from bot construction so that module-level import does not
    trigger side effects. Called once from main().
    """

    @bot.tree.command(name="prof", description="Chat with Professor Synapse")
    @app_commands.checks.cooldown(1, 60)
    async def prof_command(interaction: discord.Interaction, *, prompt: str):
        """Command handler for /prof"""
        # Validate prompt length before sending to external API
        if len(prompt) > MAX_PROMPT_LENGTH:
            error_embed = DiscordBot._create_embed(
                title="Prompt Too Long",
                description=(
                    f"Your prompt is {len(prompt)} characters. "
                    f"Please keep it under {MAX_PROMPT_LENGTH} characters."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        await bot.prof(interaction, prompt=prompt)

    @bot.tree.command(
        name="image",
        description="Generate an image using Google's Nano Banana model"
    )
    @app_commands.checks.cooldown(1, 60)
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
        # Validate prompt length before sending to external API
        if len(prompt) > MAX_PROMPT_LENGTH:
            error_embed = DiscordBot._create_embed(
                title="Prompt Too Long",
                description=(
                    f"Your prompt is {len(prompt)} characters. "
                    f"Please keep it under {MAX_PROMPT_LENGTH} characters."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
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

    # Global slash command error handler
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        """Handle errors raised by slash commands.

        Catches cooldown errors with a user-friendly wait message. All other
        unhandled errors are logged and the user receives a generic error embed
        so they never see 'Application did not respond'.
        """
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = DiscordBot._create_embed(
                title="Cooldown Active",
                description=(
                    f"This command is on cooldown. "
                    f"Please try again in **{error.retry_after:.0f}** seconds."
                ),
                color=discord.Color.orange()
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Log unexpected errors
        logger.error(
            "Unhandled error in command '%s': %s",
            interaction.command.name if interaction.command else "unknown",
            error,
            exc_info=error,
        )

        error_embed = DiscordBot._create_embed(
            title="Error",
            description="An unexpected error occurred while processing your command.",
            color=discord.Color.red()
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
        except discord.HTTPException:
            # If even the error message fails to send, just log it
            logger.error("Failed to send error response to user")


def main():
    """Application entry point. Creates the bot, registers commands, and starts the event loop."""
    bot = DiscordBot()
    _register_commands(bot)
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)
