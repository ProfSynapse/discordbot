"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities.

Features:
- Chat with AI using /prof command
- Message chunking for large responses
- Rate limiting and error handling
"""

import discord
from discord.ext import commands
import textwrap
import logging
from api_client import api_client, APIResponseError
from config import config
from scraper.scheduler import ArticleScheduler

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class DiscordBot(commands.Bot):
    """
    Custom Discord bot implementation with AI chat capabilities.
    Inherits from commands.Bot and adds custom command handling and API integration.
    """
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)
        self.scheduler = None
        
    async def setup_hook(self):
        """Initialize bot commands and scheduler on startup."""
        await self.tree.sync()
        self.scheduler = ArticleScheduler(self, config.NEWS_CHANNEL_ID)
        await self.scheduler.start()

    async def close(self):
        """Cleanup on shutdown."""
        if self.scheduler:
            await self.scheduler.stop()
        await super().close()

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Please wait {error.retry_after:.2f}s before using this command again.")
        else:
            logging.error(f"Command error: {error}")
            await ctx.send("An error occurred while processing your command.")

    async def process_data_source(self, message):
        """
        Process a message containing a URL and add it to the bot's knowledge base.
        
        Args:
            message (discord.Message): The message containing the URL to process
        """
        url = extract_url(message.content)
        if url:
            async with api_client as client:
                if await client.upload_data_source(url):
                    await message.channel.send(f"URL '{url}' has been processed.")
                else:
                    await message.channel.send("An error occurred while processing the URL.")
        else:
            await message.channel.send("No valid URL found in the message.")

    async def prof(self, interaction: discord.Interaction, *, prompt: str):
        await interaction.response.defer()
        try:
            # First, send the user's query as a message from the bot but mentioning the user
            await interaction.followup.send(f"**{interaction.user.display_name} asks:**\n{prompt}")
            
            # Get last 10 messages from the channel
            channel = interaction.channel
            messages = [msg async for msg in channel.history(limit=10)]
            messages.reverse()
            
            # Format message history
            context = "<recent_channel_conversation>\n"
            for msg in messages:
                author_name = msg.author.display_name
                # Skip bot commands and empty messages
                if not msg.content.startswith('/') and msg.content.strip():
                    context += f"{author_name}: {msg.content}\n"
            context += "</recent_channel_conversation>"
            
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                bot_response = await client.get_response(session_uuid, prompt, context)

            if not bot_response or bot_response.isspace():
                raise APIResponseError("Empty response received from API")

            # Send response in chunks
            message_chunks = chunk_message_by_paragraphs(bot_response)

            for chunk in message_chunks:
                await interaction.followup.send(chunk)

        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")
            await interaction.followup.send(
                "An error occurred while processing your request. "
                "I'll try to fix this and be back shortly!"
            )

# Create bot instance
bot = DiscordBot()

# Register the command after bot creation
@bot.tree.command(name="prof", description="Chat with Professor Synapse")
@commands.cooldown(1, 60, commands.BucketType.user)
async def prof_command(interaction: discord.Interaction, *, prompt: str):
    await bot.prof(interaction, prompt=prompt)

@bot.event
async def on_ready():
    """Event handler for when the bot is ready and connected to Discord."""
    logging.info(f'Bot is ready. Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logging.error(f"Error syncing commands: {e}")

def chunk_message_by_paragraphs(message, max_length=2000):
    """
    Splits a long message into smaller chunks based on paragraphs.

    Args:
        message (str): The message to be chunked.
        max_length (int, optional): The maximum length of each chunk. Defaults to 2000.

    Returns:
        list: A list of message chunks.
    """
    paragraphs = message.split('\n\n')
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        if len(paragraph) >= max_length:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            sub_paragraphs = textwrap.wrap(paragraph, width=max_length, replace_whitespace=False)
            chunks.extend(sub_paragraphs)
        else:
            if len(current_chunk) + len(paragraph) + 2 <= max_length:
                current_chunk += (paragraph + "\n\n")
            else:
                chunks.append(current_chunk)
                current_chunk = paragraph + "\n\n"

    if current_chunk:
        chunks.append(current_chunk)

    # Only add part numbers if there are multiple chunks
    if len(chunks) > 1:
        return [f"Part {i}/{len(chunks)}:\n{chunk}" for i, chunk in enumerate(chunks, 1)]
    return chunks

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if any(url in message.content for url in ["http://", "https://"]):
        await message.add_reaction("📚")

    await bot.process_commands(message)

@bot.event
async def on_reaction_add(reaction, user):
    if user == bot.user:
        return

    if reaction.emoji == "📚":  # Check if the reaction is the book emoji
        await process_data_source(reaction.message)

# Add error handling decorator for background tasks
def with_error_handling(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logging.error(f"Error in background task {func.__name__}: {e}")
    return wrapper

@with_error_handling
async def process_data_source(message):
    await bot.process_data_source(message)

def extract_url(message_content):
    """
    Extract the first URL found in a message.

    Args:
        message_content (str): The message content to search

    Returns:
        str|None: The first URL found or None if no URL is present
    """
    # Extract the first URL from the message content
    words = message_content.split()
    for word in words:
        if word.startswith("http://") or word.startswith("https://"):
            return word
    return None

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
