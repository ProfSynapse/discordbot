"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities.

Features:
- Chat with AI using /prof command
- Message chunking for large responses
- Rate limiting and error handling
"""

import asyncio
import re
import json
import discord
from discord.ext import commands
from discord import app_commands  # Add this import
import textwrap
import logging
from typing import List, Callable  # Remove Optional since it's unused
from api_client import api_client, APIResponseError
from config import config
from scraper.content_scheduler import ContentScheduler  # Updated import
from openai import OpenAI
from enum import Enum
from scraper.content_scraper import scrape_article_content
from functools import wraps  # Add for decorator

# Update logging configuration to include DEBUG level
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Add decorator definition
def with_error_handling(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            raise
    return wrapper

class ImageSize(Enum):
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
    """
    Custom Discord bot implementation with AI chat capabilities.
    Inherits from commands.Bot and adds custom command handling and API integration.
    """
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
        """Initialize bot commands and scheduler on startup."""
        logger.info("Starting bot setup...")
        try:
            await self.tree.sync()
            logger.info("Command tree synced")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)

    async def on_ready(self):
        """Event handler for when the bot is ready and connected to Discord."""
        try:
            logger.info(f'Bot is ready. Logged in as {self.user.name}')
            
            # Initialize unified content scheduler
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
        urls = extract_urls(message.content)  # Change to use new extract_urls function
        if urls:
            async with api_client as client:
                for url in urls:
                    if await client.upload_data_source(url):
                        await message.channel.send(f"URL '{url}' has been processed.")
                    else:
                        await message.channel.send("An error occurred while processing the URL.")
        else:
            await message.channel.send("No valid URL found in the message.")

    @staticmethod
    def format_response(text: str) -> str:
        """Extract and format the response from JSON array."""
        logger.debug("=== Raw Input ===")
        logger.debug(text)
        
        try:
            # Handle case where input is a JSON array
            if text.strip().startswith('['):
                data = json.loads(text)
                # Get the last non-empty response from the array
                for item in reversed(data):
                    if isinstance(item, dict) and item.get('response'):
                        text = item['response']
                        break
            # Handle case where input is a single JSON object
            elif text.strip().startswith('{'):
                data = json.loads(text)
                if isinstance(data, dict):
                    text = data.get('response', text)
            
            # Remove any leading/trailing whitespace while preserving internal formatting
            text = text.strip()
            
            # Preserve Discord markdown formatting
            # Don't collapse multiple newlines to preserve intentional spacing
            # Only remove spaces at the start of lines
            text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
            
        except json.JSONDecodeError:
            logger.debug("Not a JSON response, using raw text")
            text = text.strip()
        except Exception as e:
            logger.error(f"Error formatting response: {e}")
            
        logger.debug("=== Formatted Output ===")
        logger.debug(text)
        
        return text

    async def prof(self, interaction: discord.Interaction, *, prompt: str):
        await interaction.response.defer()
        try:
            # Create initial embed with question
            response_embed = discord.Embed(
                description=f"**Question:**\n{prompt}",
                color=discord.Color.blurple()
            )
            response_embed.set_footer(text=f"Asked by {interaction.user.display_name}")
            
            # Send initial embed and store message for updating
            bot_message = await interaction.followup.send(embed=response_embed)
            
            # Animate thinking state with phrases
            for phrase in self.thinking_phrases:
                response_embed.description = f"**Question:**\n{prompt}\n\n{phrase}"
                await bot_message.edit(embed=response_embed)
                await asyncio.sleep(1.5)
            
            # Get last 10 messages from the channel with improved logging
            channel = interaction.channel
            messages = [msg async for msg in channel.history(limit=10)]
            messages.reverse()
            
            # Format message history with debug logging
            context = "<recent_channel_conversation>\n"
            message_count = 0
            
            for msg in messages:
                author_name = msg.author.display_name
                # Skip bot command messages and empty messages
                if not msg.content.startswith('/') and msg.content.strip():
                    context += f"{author_name}: {msg.content}\n"
                    message_count += 1
            context += "</recent_channel_conversation>"
            
            # Debug logging for context
            logger.info(f"Built context with {message_count} messages")
            logger.debug("=== Conversation Context ===")
            logger.debug(context)
            logger.debug("=== End Context ===")
            
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                logger.info(f"Created session: {session_uuid}")
                
                # Log the entire request
                logger.debug(f"Sending request - Prompt: {prompt}")
                logger.debug(f"Context length: {len(context)}")
                
                bot_response = await client.get_response(session_uuid, prompt, context)
                
                # Enhanced logging
                logger.info("=== Raw AI Response ===")
                logger.info(bot_response)
                logger.info("=== End Raw Response ===")
                
                # Also log to console for immediate visibility
                print("\n=== Raw AI Response ===")
                print(bot_response)
                print("=== End Raw Response ===\n")

            if not bot_response or bot_response.isspace():
                raise APIResponseError("Empty response received from API")

            # Format the response
            formatted_response = self.format_response(bot_response)
            
            # Create final embed combining question and answer
            response_embed = discord.Embed(
                color=discord.Color.green()
            )
            response_embed.add_field(
                name="Question",
                value=prompt,
                inline=False
            )
            response_embed.add_field(
                name="Response",
                value=formatted_response,
                inline=False
            )
            response_embed.set_footer(text=f"Asked by {interaction.user.display_name}")
            
            # Update the message with final response
            await bot_message.edit(embed=response_embed)

        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")
            error_embed = discord.Embed(
                title="❌ Error",
                description="An error occurred while processing your request. I'll try to fix this and be back shortly!",
                color=discord.Color.red()
            )
            if 'bot_message' in locals():
                await bot_message.edit(embed=error_embed)
            else:
                await interaction.followup.send(embed=error_embed)

    async def generate_image(self, interaction: discord.Interaction, prompt: str, size: ImageSize = ImageSize.SQUARE):
        """Generate an image using DALL-E 3"""
        await interaction.response.defer()
        
        # Send the "preparing" message
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
            # More artistic response format with cleaner URL presentation
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

# Add at the top level, after imports
PROCESSED_URLS = set()

# Create bot instance before event handlers
bot = DiscordBot()

# Replace on_message event handler
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Check for URLs in message content
    urls = extract_urls(message.content)  # New function to extract all URLs
    if urls:
        for url in urls:
            await message.add_reaction("📥")

    await bot.process_commands(message)

# Replace on_reaction_add event handler
@bot.event
async def on_reaction_add(reaction, user):
    """Handle reaction events for article processing."""
    if user == bot.user:
        return

    if reaction.emoji == "📥":
        urls = []
        message = reaction.message
        
        # Check embeds first
        if message.embeds:
            embed = message.embeds[0]
            if embed.url:
                urls.append(embed.url)
                
        # Then check message content
        content_urls = extract_urls(message.content)
        urls.extend(content_urls)
        
        if urls:
            for url in urls:
                if url not in PROCESSED_URLS:
                    try:
                        # Remove the reaction to show we're processing
                        await reaction.remove(user)
                        # Add a "loading" reaction
                        await message.add_reaction("⏳")
                        
                        # Process the URL
                        await process_data_source(message, url)
                        
                        # Remove loading reaction
                        await message.remove_reaction("⏳", bot.user)
                        # Add success reaction
                        await message.add_reaction("✅")
                        
                    except Exception as e:
                        logger.error(f"Error processing URL {url}: {e}")
                        await message.remove_reaction("⏳", bot.user)
                        await message.add_reaction("❌")
                        continue

# Update extract_url function to extract_urls (plural)
def extract_urls(message_content: str) -> List[str]:
    """Extract all URLs from a message."""
    words = message_content.split()
    return [word for word in words if word.startswith(("http://", "https://"))]

# Update process_data_source to take explicit URL parameter
@with_error_handling
async def process_data_source(message, url: str):
    """Process a message containing a URL."""
    if url in PROCESSED_URLS:
        await message.channel.send(f"📚 I've already processed {url}")
        return
        
    processing_msg = await message.channel.send(f"📤 Processing article from {url}...")
    
    try:
        # Step 1: Scrape the article content
        content = await scrape_article_content(url)
        if not content:
            await processing_msg.edit(content=f"❌ Could not extract content from {url}")
            return

        # Step 2: Generate article summary
        async with api_client as client:
            summary_result = await client.summarize_content(url, content)
            
            if summary_result.get('success'):
                summary = summary_result['summary']
                # Format the summary as an embed without the reaction footer
                embed = discord.Embed(
                    title="📝 Article Summary",
                    description=summary,
                    color=discord.Color.blue(),
                    url=url
                )
                await message.channel.send(embed=embed)
            else:
                logger.error(f"Failed to generate summary: {summary_result.get('error')}")
                
            # Step 3: Upload to knowledge base
            logger.info(f"Uploading URL to GPT Trainer: {url}")
            upload_result = await client.upload_data_source(url)
            
            if not upload_result.get('success'):
                error_msg = upload_result.get('error', 'Unknown error')
                logger.error(f"Failed to upload to knowledge base: {error_msg}")
                await processing_msg.edit(content=f"❌ Failed to add to my knowledge base: {error_msg}")
                return
                
            # Handle case where URL already exists
            if upload_result.get('existing'):
                await processing_msg.edit(content="📚 This article is already in my knowledge base!")
            else:
                await processing_msg.edit(content=f"✅ Added to my knowledge base: {url}")
            
            PROCESSED_URLS.add(url)

    except Exception as e:
        logger.error(f"Error in process_data_source: {e}", exc_info=True)
        await processing_msg.edit(content=f"❌ Error: {str(e)}")

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

# Register the command after bot creation
@bot.tree.command(name="prof", description="Chat with Professor Synapse")
@commands.cooldown(1, 60, commands.BucketType.user)
async def prof_command(interaction: discord.Interaction, *, prompt: str):
    await bot.prof(interaction, prompt=prompt)

@bot.tree.command(name="image", description="Generate an image using DALL-E (add --square, --portrait, or --wide to change format)")
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
