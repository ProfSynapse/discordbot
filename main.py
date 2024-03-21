import discord
from discord.ext import commands
from discord import app_commands
import os
from discord_api import create_chat_session, gpt_response
import textwrap
import logging
from conversation_history import update_conversation_history, get_user_context
from data_source import upload_data_source
import datetime
from bs4 import BeautifulSoup
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DISCORD_TOKEN = os.environ['DISCORD_TOKEN']
GPT_TRAINER_TOKEN = os.environ['GPT_TRAINER_TOKEN']
CHATBOT_UUID = os.environ['CHATBOT_UUID']

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

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

async def process_data_source(message):
    # Extract the URL from the message content
    url = extract_url(message.content)

    if url:
        try:
            # Upload the data source to the bot's knowledge base
            upload_data_source(url)
            await message.channel.send(f"Data source '{url}' has been added to the bot's knowledge base.")
        except Exception as e:
            logging.error(f"Error uploading data source: {str(e)}")
            await message.channel.send("An error occurred while uploading the data source.")
    else:
        await message.channel.send("No valid URL found in the message.")

def extract_url(message_content):
    # Extract the first URL from the message content
    words = message_content.split()
    for word in words:
        if word.startswith("http://") or word.startswith("https://"):
            return word
    return None

@bot.tree.command(name="prof", description="Chat with Professor Synapse")
async def prof(interaction: discord.Interaction, *, prompt: str):
    """
    Slash command to interact with the GPT Trainer API and generate a response.

    Args:
        interaction (discord.Interaction): The interaction object representing the command invocation.
        prompt (str): The user's input prompt.
    """
    await interaction.response.defer()
    try:
        # Get the user's ID
        user_id = str(interaction.user.id)

        # Get the user's context based on their conversation history
        user_context = get_user_context(user_id)

        # Update the conversation history with the user's prompt
        update_conversation_history(user_id, f"User: {prompt}")

        # Create a chat session and get the response
        session_uuid = create_chat_session()
        bot_response = gpt_response(session_uuid, f"{user_context}\nUser: {prompt}")

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

bot.run(DISCORD_TOKEN)
