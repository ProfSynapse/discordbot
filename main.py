import discord
from discord.ext import commands
from discord import app_commands
import os
from discord_api import create_chat_session, gpt_response
import textwrap
import logging

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
        # Validate and sanitize the user input
        prompt = prompt.strip()
        if not prompt:
            await interaction.followup.send("Please provide a valid prompt.")
            return

        # Create a chat session and get the response
        session_uuid = create_chat_session()
        bot_response = gpt_response(session_uuid, prompt)

        # Combine the query and the response
        full_message = f"**Query:**\n{prompt}\n\n{bot_response}"
        message_chunks = chunk_message_by_paragraphs(full_message)

        # Send each chunk as a separate message
        for chunk in message_chunks:
            await interaction.followup.send(chunk)

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        await interaction.followup.send("An error occurred while processing your request. Please try again later.")

bot.run(DISCORD_TOKEN)
