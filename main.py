"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities
and manages URL-based knowledge base updates.

Features:
- Chat with AI using /prof command
- Process and summarize URLs using /sum command
- Automatic URL detection and processing
- Message chunking for large responses
- Rate limiting and error handling
"""

import discord
from discord.ext import commands
from discord import app_commands
import os
from api_client import api_client
import textwrap
import logging
from conversation_history import update_conversation_history, get_user_context
import datetime
from bs4 import BeautifulSoup
import requests
import asyncio
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

    @bot.tree.command(name="prof", description="Chat with Professor Synapse")
    @commands.cooldown(1, 60, commands.BucketType.user)  # Rate limit: 1 use per minute per user
    async def prof(self, interaction: discord.Interaction, *, prompt: str):
        await interaction.response.defer()
        try:
            user_id = str(interaction.user.id)
            user_context = get_user_context(user_id)
            
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                bot_response = await client.get_response(session_uuid, prompt, user_context)

            # Update the conversation history with the user's prompt
            update_conversation_history(user_id, f"User: {prompt}")

            # Update the conversation history with the bot's response
            update_conversation_history(user_id, f"Assistant: {bot_response}")

            # Combine the query and the response
            full_message = f"**Query:**\n{prompt}\n\n{bot_response}"
            message_chunks = chunk_message_by_paragraphs(full_message)

            # Send each chunk as a separate message
            for chunk in message_chunks:
                await interaction.followup.send(chunk)

        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")
            await interaction.followup.send("An error occurred while processing your request. Please try again later.")

# Create bot instance
bot = DiscordBot()

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

    chunked_messages = []
    for i, chunk in enumerate(chunks, 1):
        chunk_prefix = f"Part {i}/{len(chunks)}:\n"
        if len(chunk) + len(chunk_prefix) > max_length:
            first_line_len = max_length - len(chunk_prefix)
            chunked_messages.append(chunk_prefix + chunk[:first_line_len])
            chunked_messages.extend(textwrap.wrap(chunk[first_line_len:], max_length))
        else:
            chunked_messages.append(chunk_prefix + chunk)

    return chunked_messages

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if any(url in message.content for url in ["http://", "https://"]):
        await message.add_reaction("📚")  # Add a book emoji to messages containing a URL

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

def get_metadata(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.content, 'html.parser')

        title = soup.find('title').text.strip() if soup.find('title') else ''
        description = soup.find('meta', attrs={'name': 'description'})['content'].strip() if soup.find('meta', attrs={'name': 'description'}) else ''

        return title, description
    except Exception as e:
        logging.exception(f"Error occurred while retrieving metadata for URL '{url}': {str(e)}")
        return '', ''

@bot.tree.command(name="sum", description="Summarize links from the previous week")
async def sum(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        one_week_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=1)
        links = []

        for channel in interaction.guild.text_channels:
            async for message in channel.history(limit=None, after=one_week_ago):
                if message.author != bot.user and any(url in message.content for url in ["http://", "https://"]):
                    links.append(message.content)

        if links:
            link_metadata = []
            for link in links:
                title, description = get_metadata(link)
                link_metadata.append(f"Link: {link}\nTitle: {title}\nDescription: {description}")

            link_metadata_str = "\n\n".join(link_metadata)

            session_uuid = create_chat_session()
            prompt = f"Provide the links and a one-sentence description for each of the following links based on their title and description:\n\n{link_metadata_str}"
            bot_response = gpt_response(session_uuid, prompt)

            summary_message = "**Link Summaries (Previous Week):**\n" + bot_response
            message_chunks = chunk_message_by_paragraphs(summary_message)

            for chunk in message_chunks:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send("No links found in the channels for the previous week.")

    except Exception as e:
        logging.exception(f"Error occurred in /sum command: {str(e)}")
        await interaction.followup.send("An error occurred while processing the /sum command. Please check the bot logs for more information.")

if __name__ == "__main__":
    bot.run(config.DISCORD_TOKEN)
