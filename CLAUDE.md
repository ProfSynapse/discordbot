# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Discord bot that integrates with GPT Trainer API for conversational AI capabilities and Google's Imagen 4 for AI image generation. It also features optional automated content scheduling that scrapes AI news from RSS feeds and monitors YouTube channels.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Bot
```bash
# Run the main bot
python main.py

# Run configuration tests (recommended before first run)
python test_bot.py

# Run API integration tests (makes real API calls - use with caution)
python test_apis.py
```

### Environment Variables
Required variables in `.env`:
- `DISCORD_TOKEN` - Discord bot authentication token
- `GPT_TRAINER_TOKEN` - GPT Trainer API token
- `CHATBOT_UUID` - GPT Trainer chatbot UUID
- `GOOGLE_API_KEY` - Google API key for Imagen 4

Optional variables for content scheduling:
- `CONTENT_CHANNEL_ID` - Discord channel ID for automated content posting
- `YOUTUBE_API_KEY` - YouTube Data API key

## Architecture

### Core Components

**main.py** - Primary Discord bot implementation
- `DiscordBot` class extends `commands.Bot`
- Implements two slash commands: `/prof` (chat) and `/image` (image generation)
- Manages optional `ContentScheduler` initialization based on environment config
- Uses async/await pattern throughout for Discord.py 2.x compatibility
- Cooldowns: Both commands have 60-second per-user cooldown

**api_client.py** - GPT Trainer API client
- `GPTTrainerAPI` singleton class with async context manager support
- Connection pooling via aiohttp.ClientSession
- Implements exponential backoff retry logic (3 retries by default)
- Streaming response support for chat completions
- Key methods: `create_chat_session()`, `get_response()`, `upload_data_source()`

**image_generator.py** - Google Imagen 4 integration
- `ImageGenerator` class handles all image generation
- Enum-based configuration: `ImageModel`, `ImageSize`, `ImageFormat`
- Flag parsing from user prompts (e.g., `--ultra`, `--2k`, `--png`)
- Model variants:
  - FAST: Fixed default size, fastest generation
  - STANDARD: Supports 1K/2K sizes, balanced quality
  - ULTRA: Highest quality, supports 1K/2K sizes

**config.py** - Configuration management
- `BotConfig` dataclass with type hints
- Loads from environment via `BotConfig.from_env()`
- All config accessed via singleton: `from config import config`

### Content Scheduling System

**scraper/content_scheduler.py** - Main scheduler orchestration
- `ContentScheduler` class manages two separate content streams:
  - News articles from RSS feeds
  - YouTube videos from monitored channels
- Maintains two queues: `news_queue` and `youtube_queue`
- Posts content to single Discord channel specified by `CONTENT_CHANNEL_ID`
- Automatically uploads all posted content to GPT Trainer knowledge base via `_upload_to_gpt_trainer()`
- Tracks seen content to prevent duplicates using:
  - `seen_videos.json` file for YouTube videos
  - `posted_urls` set for news articles (rebuilt from channel history on startup)
- Background tasks run on intervals: news every 2-6 hours, YouTube every 1-3 hours

**scraper/news_scraper.py** - RSS feed scraping
- `scrape_all_sites()` fetches from all feeds in `RSS_FEEDS` dict
- Filters articles by AI keywords and recency (last 48 hours)
- Supports multiple date formats via `parse_date()` function
- Returns list of article dicts with `title`, `url`, `published`, `source`

**scraper/content_scraper.py** - Web content extraction
- `scrape_article_content()` extracts article text from URLs
- Uses BeautifulSoup with multiple content selector strategies
- Implements retry logic with exponential backoff
- Cleans content by removing scripts, styles, ads, emails, URLs

### Key Design Patterns

**Async/Await Throughout**
All I/O operations (Discord API, HTTP requests, API calls) use async/await. Never mix sync and async code without proper event loop handling.

**Error Handling**
- `@with_error_handling` decorator wraps async functions in main.py
- API client implements retry logic with exponential backoff
- All errors logged to both console and `bot.log` file

**Configuration**
All configuration comes from `config.py`. Never access `os.environ` directly elsewhere. Use `config.VARIABLE_NAME`.

**Singleton Pattern**
Both `api_client` and `config` are singleton instances exported from their modules.

## Common Workflows

### Adding a New Discord Command

1. Define async method on `DiscordBot` class in main.py
2. Register command using `@bot.tree.command()` decorator at module level
3. Apply cooldown with `@commands.cooldown()` if needed
4. Follow pattern: defer interaction, send thinking message, process, edit message

### Modifying Content Sources

**Add RSS feed:** Edit `RSS_FEEDS` dict in `scraper/news_scraper.py`
```python
"Source Name": {
    "url": "https://example.com/feed",
    "date_format": "rfc822"  # or "arxiv" for special formats
}
```

**Add YouTube channel:** Edit `YOUTUBE_CHANNELS` dict in `scraper/content_scheduler.py`
```python
"Channel Name": "CHANNEL_ID_HERE"
```

### Working with Image Generation

Parse user flags with `ImageGenerator.parse_flags()` which returns clean prompt and `ImageConfig` object. Always handle the model-specific size limitations (FAST model doesn't accept size parameter).

### API Integration Points

**GPT Trainer:**
- Chat: `create_chat_session()` → `get_response(session_uuid, message, context)`
- Knowledge base: `upload_data_source(url)`

**Google Imagen:**
- Generate: `client.models.generate_images(model, prompt, config)`
- Returns `GenerateImagesResponse` with `generated_images[0].image.image_bytes`

## Testing

The codebase includes two test suites:

**test_bot.py** - Configuration validation (free)
- Checks environment variables
- Validates dependencies
- Tests API connectivity

**test_apis.py** - Integration tests (makes real API calls)
- Tests GPT Trainer chat and knowledge base
- Tests all 3 Imagen models
- Tests content scraping
- Run with `--yes` flag to skip confirmations

## Code Conventions

- Async functions for all I/O operations
- Type hints on function signatures
- Docstrings on classes and complex functions
- Logging via module-level logger: `logger = logging.getLogger(__name__)`
- Discord embeds for formatted responses
- Command names use lowercase (e.g., `/prof`, `/image`)
