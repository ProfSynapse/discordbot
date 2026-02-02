"""
Location: /mnt/f/Code/discordbot/main.py
Summary: Main Discord bot module that handles all Discord-specific functionality.
         This bot integrates with GPT Trainer API to provide conversational AI capabilities.
         Defines the DiscordBot class (commands.Bot subclass) and provides the main() entry point.

Used by: Executed directly as the application entry point.
Uses: api_client.py (API calls), config.py (settings), session_manager.py (session
      persistence), image_generator.py (image generation), scraper/ (content scheduling),
      health_check.py (HTTP health endpoint for Docker/Railway), commands.py (slash commands),
      gallery.py (image gallery posting), memory/ (conversational memory pipeline).
"""

# Load environment variables from .env file BEFORE any other imports
# This must come first because config.py reads os.environ at import time
from dotenv import load_dotenv
load_dotenv()

import asyncio
import discord
from discord.ext import commands
import logging
import io
import random
from typing import Optional
from api_client import api_client
from config import config
from scraper.content_scheduler import ContentScheduler
from image_generator import ImageGenerator
from session_manager import SessionManager
from health_check import HealthCheckServer
from citation_handler import fetch_and_process_citations
from commands import register_commands
from gallery import post_to_gallery
from utils.constants import MAX_PROMPT_LENGTH, MAX_CONTEXT_CHARS, THINKING_PHRASES
from utils.decorators import with_error_handling
from utils.text_formatting import split_response
from memory import ConversationMemoryPipeline

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class DiscordBot(commands.Bot):
    """Discord bot implementation with streamlined message handling."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)

        self.scheduler = None
        self.health_server: Optional[HealthCheckServer] = None
        self.session_manager: Optional[SessionManager] = None
        self.memory_pipeline: Optional[ConversationMemoryPipeline] = None
        self.image_generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
        self._last_bot_message_id: dict[int, int] = {}  # channel_id -> message_id
        # Format thinking phrases with emoji and italic markdown for Discord display
        self.thinking_phrases = [f"*{phrase}*" for phrase in THINKING_PHRASES]

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

        # Initialize memory pipeline if enabled (non-fatal)
        if config.MEMORY_ENABLED:
            try:
                self.memory_pipeline = ConversationMemoryPipeline(
                    api_key=config.GOOGLE_API_KEY,
                    api_client=api_client,
                    enabled_channels=config.MEMORY_ENABLED_CHANNELS,
                    data_dir=config.MEMORY_DATA_DIR,
                    db_path=config.MEMORY_DB_PATH,
                    check_interval=config.MEMORY_CHECK_INTERVAL,
                    max_buffer_size=config.MEMORY_MAX_BUFFER_SIZE,
                    time_gap_threshold=config.MEMORY_TIME_GAP_THRESHOLD
                )
                await self.memory_pipeline.initialize()

                # Set up channel name resolver using the bot's cache
                async def resolve_channel_name(channel_id: str) -> str:
                    channel = self.get_channel(int(channel_id))
                    if channel and hasattr(channel, 'name'):
                        return channel.name
                    return f"channel-{channel_id}"

                self.memory_pipeline.set_channel_name_resolver(resolve_channel_name)
                logger.info(
                    f"Memory pipeline initialized for channels: {config.MEMORY_ENABLED_CHANNELS}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize memory pipeline: {e}", exc_info=True)
                self.memory_pipeline = None
        else:
            logger.info("Memory pipeline disabled (MEMORY_ENABLED=false)")

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

            # Start memory pipeline background task
            if self.memory_pipeline:
                await self.memory_pipeline.start()
                logger.info("Memory pipeline background task started")

        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)

    async def close(self):
        """Cleanup resources on shutdown."""
        # Stop memory pipeline and force-chunk any remaining conversations
        if self.memory_pipeline:
            try:
                chunks_created = await self.memory_pipeline.force_chunk_all()
                if chunks_created > 0:
                    logger.info(f"Created {chunks_created} chunk(s) on shutdown")
                await self.memory_pipeline.stop()
            except Exception as e:
                logger.error(f"Error stopping memory pipeline: {e}", exc_info=True)

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
        # Track message in memory pipeline (before any returns)
        # This captures all messages in enabled channels for topic detection
        if self.memory_pipeline:
            self.memory_pipeline.track_message(message)

        # Ignore messages from bots (including self) to prevent loops
        if message.author.bot:
            return

        # Auto-upload links in configured channels
        if message.channel.id in config.KNOWLEDGE_BASE_CHANNEL_IDS:
            from link_handler import handle_link_message
            await handle_link_message(message)

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
                    # Upload any URLs to knowledge base FIRST, so the bot can
                    # reference the content in its response
                    from link_handler import upload_urls_from_content
                    uploaded, failed = await upload_urls_from_content(clean_content)
                    if uploaded > 0:
                        logger.info(f"Uploaded {uploaded} URL(s) from mention before processing")

                    async with api_client as client:
                        # Get or create persistent session for this user
                        user_id = str(message.author.id)
                        session_uuid = await self.session_manager.get_or_create_session(user_id)

                        # Optionally build context from recent channel messages
                        context = ""
                        if config.USE_CHANNEL_CONTEXT:
                            context = await self._build_channel_context(
                                message.channel
                            )

                        # Get response (session maintains user's conversation history)
                        response = await client.get_response(
                            session_uuid, clean_content, context
                        )

                        # Process citations: fetch cite_data_json from the
                        # session messages and transform [X.Y] markers.
                        response = await fetch_and_process_citations(
                            client, session_uuid, response
                        )

                        # Split into Discord-safe chunks and send as replies
                        chunks = split_response(response)

                        # First chunk is a direct reply to the user's message,
                        # creating a visible reply chain in Discord
                        sent_message = await message.reply(chunks[0])

                        # Subsequent chunks are sent as plain channel messages to
                        # avoid stacking multiple reply indicators
                        for chunk in chunks[1:]:
                            sent_message = await message.channel.send(chunk)

                        # Track the bot's last response in this channel so
                        # _build_channel_context can fetch only newer messages
                        self._last_bot_message_id[message.channel.id] = sent_message.id

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

                # Optionally build context from recent channel messages
                context = ""
                if config.USE_CHANNEL_CONTEXT:
                    context = await self._build_channel_context(interaction.channel)

                # Get response (session maintains user's conversation history)
                response = await client.get_response(session_uuid, prompt, context)

                # Process citations: fetch cite_data_json from the session
                # messages and transform [X.Y] markers into links or strip them.
                response = await fetch_and_process_citations(
                    client, session_uuid, response
                )

                # Split the response into Discord-safe chunks and send as plain text
                chunks = split_response(response)

                # Edit the thinking message with the first chunk
                await bot_message.edit(content=chunks[0])
                last_sent = bot_message

                # Send any remaining chunks as followup messages
                for chunk in chunks[1:]:
                    last_sent = await interaction.followup.send(chunk, wait=True)

                # Track the bot's last response in this channel so
                # _build_channel_context can fetch only newer messages
                self._last_bot_message_id[interaction.channel_id] = last_sent.id

        except Exception as e:
            logger.error(f"Error in prof: {e}", exc_info=True)
            await bot_message.edit(
                content="Sorry, I ran into an issue processing that. Please try again."
            )

    async def _build_channel_context(
        self,
        channel: discord.TextChannel,
        limit: int = None
    ) -> str:
        """Build context from channel messages since the bot's last response.

        Fetches messages posted after the bot's most recent reply in this
        channel, giving the bot awareness of everything said between its
        invocations (all users included).  On the first invocation in a
        channel (no tracked last-response), falls back to fetching recent
        messages.

        Results are capped at ``limit`` messages (default
        ``config.CHANNEL_CONTEXT_LIMIT``) and ``MAX_CONTEXT_CHARS`` total
        characters.  When the total text exceeds the character limit the
        oldest collected messages are dropped first.
        """
        if limit is None:
            limit = config.CHANNEL_CONTEXT_LIMIT

        last_msg_id = self._last_bot_message_id.get(channel.id)

        context = []
        if last_msg_id is not None:
            # Fetch messages AFTER the bot's last response.  When ``after``
            # is provided, discord.py returns messages in chronological
            # order (oldest first) by default, so no reversal is needed.
            async for msg in channel.history(limit=limit * 2,
                                             after=discord.Object(id=last_msg_id)):
                if msg.author.bot:
                    continue
                if msg.content.startswith('/'):
                    continue
                if not msg.content.strip():
                    continue
                context.append(f"{msg.author.display_name}: {msg.content}")
                if len(context) >= limit:
                    break
        else:
            # First time in this channel -- fall back to recent history.
            # channel.history without ``after`` returns newest-first, so
            # we reverse afterwards.
            async for msg in channel.history(limit=limit * 2):
                if msg.author.bot:
                    continue
                if msg.content.startswith('/'):
                    continue
                if not msg.content.strip():
                    continue
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
        await interaction.followup.send("*Consulting the AI art masters...*")

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
                f"**A masterpiece commissioned by {interaction.user.display_name}:**\n"
                f"*{clean_prompt}*",
                file=file
            )

            # Fire-and-forget: cross-post to gallery channel if configured
            if config.IMAGE_GALLERY_CHANNEL_ID:
                asyncio.create_task(
                    post_to_gallery(
                        bot=self,
                        image_data=image_data,
                        prompt=clean_prompt,
                        user=interaction.user,
                        aspect_ratio=img_config.aspect_ratio.value
                    )
                )

        except Exception as e:
            logger.error(f"Image generation error: {str(e)}")
            await interaction.followup.send(
                "*I apologize, but I encountered an issue creating your image.*"
            )


def main():
    """Application entry point. Creates the bot, registers commands, and starts the event loop."""
    bot = DiscordBot()
    register_commands(bot)
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        print("Discord package not found. Please install it using:")
        print("pip install discord.py")
        exit(1)
