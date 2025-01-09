"""
Main Discord bot module that handles all Discord-specific functionality.
This bot integrates with GPT Trainer API to provide conversational AI capabilities.

Features:
- Chat with AI using /prof command
- Message chunking for large responses
- Rate limiting and error handling
"""

import re
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
        """Format the response text to ensure proper line breaks and spacing."""
        logger.debug("=== Raw Response Before Formatting ===")
        logger.debug(text)
        logger.debug("=====================================")
        
        # First, normalize newlines
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Add these cleanup rules near the start of the method
        text = re.sub(r'(?<=\w)\s+(?=[,\.])', '', text)  # Remove spaces before punctuation
        text = re.sub(r'(?<=[:;])\s*\n*\s*(?=[A-Za-z])', '\n\n', text)  # Add proper newlines after colons
        text = re.sub(r'\s+([,.!?])', r'\1', text)  # Remove spaces before punctuation
        text = re.sub(r'\s{2,}', ' ', text)  # Replace multiple spaces with single space

        # Handle special characters and emojis
        emoji_map = {
            '🧙': '\n🧙',  # Add newline before wizard emoji
            '•': '\n•',    # Add newline before bullets
            '1.': '\n1.',  # Add newline before numbered lists
            '2.': '\n2.',
            '3.': '\n3.',
            '4.': '\n4.',
            '5.': '\n5.',
            '*': '\n*',    # Add newline before asterisks
            '🎨': '\n🎨',  # Add newline before palette emoji
        }
        
        # Apply emoji formatting
        for emoji, replacement in emoji_map.items():
            text = text.replace(f' {emoji}', replacement)
        
        # Special handling for code blocks
        code_blocks = []
        text = re.sub(r'```(?:\w+)?\n(.*?)\n```', 
                     lambda m: code_blocks.append(m.group(0)) and f'CODE_BLOCK_{len(code_blocks)-1}', 
                     text, flags=re.DOTALL)
        
        # Handle bullet points and lists
        text = re.sub(r'(?:^|\n)\s*[-•]\s*', '\n• ', text, flags=re.MULTILINE)
        text = re.sub(r'(?:^|\n)\s*(\d+\.)\s*', r'\n\1 ', text, flags=re.MULTILINE)
        
        # Handle section headers with proper spacing
        text = re.sub(r'(?:^|\n)([A-Za-z\s]+:)\s*', r'\n\n\1\n', text)
        
        # Clean up multiple spaces while preserving intentional newlines
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Restore code blocks
        for i, block in enumerate(code_blocks):
            text = text.replace(f'CODE_BLOCK_{i}', f'\n{block}\n')
        
        # Ensure proper spacing for sections and lists
        text = text.replace('\n•', '\n\n•')
        text = text.replace('\n*', '\n\n*')
        text = re.sub(r'(?<=:)\n(?=\s*[•\d])', '\n\n', text)  # Add space after section headers
        
        # Remove extra spaces after bullets and numbers
        text = re.sub(r'•\s+', '• ', text)
        text = re.sub(r'(\d+\.)\s+', r'\1 ', text)
        
        # Clean up final result
        text = text.strip()
        
        logger.debug("=== Formatted Response ===")
        logger.debug(text)
        logger.debug("=========================")
        
        return text

    async def prof(self, interaction: discord.Interaction, *, prompt: str):
        await interaction.response.defer()
        try:
            # First, send the user's query as an embed
            query_embed = discord.Embed(
                title="🤔 Question",
                description=prompt,
                color=discord.Color.blurple()
            )
            query_embed.set_footer(text=f"Asked by {interaction.user.display_name}")
            await interaction.followup.send(embed=query_embed)
            
            # Get last 10 messages from the channel
            channel = interaction.channel
            messages = [msg async for msg in channel.history(limit=10)]
            messages.reverse()
            
            # Format message history
            context = "<recent_channel_conversation>\n"
            for msg in messages:
                author_name = msg.author.display_name
                if not msg.content.startswith('/') and msg.content.strip():
                    context += f"{author_name}: {msg.content}\n"
            context += "</recent_channel_conversation>"
            
            async with api_client as client:
                session_uuid = await client.create_chat_session()
                bot_response = await client.get_response(session_uuid, prompt, context)
                
                logger.debug("=" * 50)
                logger.debug("Raw bot response received:")
                logger.debug(bot_response)
                logger.debug("=" * 50)

            if not bot_response or bot_response.isspace():
                raise APIResponseError("Empty response received from API")

            # Format the response
            formatted_response = self.format_response(bot_response)
            
            # Create response embed without title
            response_embed = discord.Embed(
                description=formatted_response,
                color=discord.Color.green()
            )
            
            # Split response into chunks if needed
            if len(formatted_response) > 4096:  # Discord's embed description limit
                chunks = chunk_message_by_paragraphs(formatted_response)
                for i, chunk in enumerate(chunks, 1):
                    chunk_embed = discord.Embed(
                        description=chunk,
                        color=discord.Color.green()
                    )
                    await interaction.followup.send(embed=chunk_embed)
            else:
                await interaction.followup.send(embed=response_embed)

        except Exception as e:
            logging.error(f"An error occurred: {str(e)}")
            error_embed = discord.Embed(
                title="❌ Error",
                description="An error occurred while processing your request. I'll try to fix this and be back shortly!",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed)  # Fixed syntax error here

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
                # Format the summary as an embed
                embed = discord.Embed(
                    title="📝 Article Summary",
                    description=summary,
                    color=discord.Color.blue(),
                    url=url
                )
                embed.set_footer(text="React with 📥 to add to my knowledge base")
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
