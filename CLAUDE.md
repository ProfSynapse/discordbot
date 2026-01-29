# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Discord bot that integrates with GPT Trainer API for conversational AI capabilities and Google's Gemini for AI image generation. It also features optional automated content scheduling that scrapes AI news from RSS feeds and monitors YouTube channels.

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
- `GOOGLE_API_KEY` - Google API key for Gemini

Optional variables:
- `IMAGE_GALLERY_CHANNEL_ID` - Forum channel ID for auto-posting generated images
- `CONTENT_CHANNEL_ID` - Discord channel ID for automated content posting
- `YOUTUBE_API_KEY` - YouTube Data API key

## Architecture

### Core Components

**main.py** - Bot initialization and core class
- `DiscordBot` class extends `commands.Bot`
- Handles bot lifecycle: `setup_hook()`, `on_ready()`, `close()`
- Message handling via `on_message()` for non-command interactions
- Core command logic: `prof()`, `generate_image()`

**commands.py** - Slash command handlers
- `register_commands(bot)` - Registers all slash commands on bot's command tree
- `/prof` - Chat command handler
- `/image` - Image generation command handler
- `/reset` - Session reset command handler
- `/sessioninfo` - Session info command handler
- Global error handler for slash commands

**gallery.py** - Forum gallery posting
- `post_to_gallery()` - Posts generated images to forum channel as new threads

**api_client.py** - GPT Trainer API client
- `GPTTrainerAPI` singleton class with async context manager support
- Connection pooling via aiohttp.ClientSession
- Implements exponential backoff retry logic (3 retries by default)
- Key methods: `create_chat_session()`, `get_response()`, `upload_data_source()`

**image_generator.py** - Google Gemini image generation
- `ImageGenerator` class using `gemini-2.5-flash-image` model
- `AspectRatio` enum for aspect ratio options
- `parse_flags()` extracts flags like `--wide`, `--tall` from prompts
- Only supports `aspect_ratio` parameter (not `image_size`)

**config.py** - Configuration management
- `BotConfig` dataclass with type hints
- Loads from environment via `BotConfig.from_env()`
- All config accessed via singleton: `from config import config`

**utils/** - Shared utilities
- `constants.py` - MAX_PROMPT_LENGTH, MAX_CONTEXT_CHARS, THINKING_PHRASES
- `decorators.py` - `@with_error_handling` decorator
- `text_formatting.py` - `split_response()`, `truncate_response()`, `create_embed()`

### Content Scheduling System

**scraper/content_scheduler.py** - Main scheduler orchestration
- `ContentScheduler` class manages news articles and YouTube videos
- Posts content to single Discord channel specified by `CONTENT_CHANNEL_ID`
- Automatically uploads all posted content to GPT Trainer knowledge base
- Tracks seen content in SQLite `seen_content` table

**scraper/news_scraper.py** - RSS feed scraping
- `scrape_all_sites()` fetches from all feeds in `RSS_FEEDS` dict
- Filters articles by AI keywords and recency (last 48 hours)

**scraper/content_scraper.py** - Web content extraction
- `scrape_article_content()` extracts article text from URLs
- Uses BeautifulSoup with multiple content selector strategies

## Critical Gotchas

### ForumChannel.create_thread Requires Content
Discord.py's `ForumChannel.create_thread()` requires the `content` parameter even though docs say it's optional. Without it, you get a 400 "Cannot send an empty message" error.
```python
# WRONG - will fail with 400 error
await forum.create_thread(name="Title", embed=embed, file=file)

# CORRECT - must include content
await forum.create_thread(name="Title", content="Text", embed=embed, file=file)
```
See: https://github.com/Rapptz/discord.py/discussions/9185

### Gemini Image Model Limitations
The `gemini-2.5-flash-image` model only supports `aspect_ratio` in ImageConfig. The `image_size` parameter is NOT supported and will cause a 400 INVALID_ARGUMENT error.
```python
# CORRECT - aspect_ratio only
config=types.GenerateContentConfig(
    response_modalities=["IMAGE"],
    image_config=types.ImageConfig(aspect_ratio="16:9")
)
```

### Config Singleton Executes at Import Time
`config.py` calls `BotConfig.from_env()` at module level, which means environment variables must be set BEFORE importing any module that imports config. For testing, set dummy env vars in `conftest.py` before imports.

## Common Workflows

### Adding a New Discord Command

1. Add command logic method to `DiscordBot` class in `main.py`
2. Add command handler in `commands.py` using `@bot.tree.command()` decorator
3. Apply cooldown with `@app_commands.checks.cooldown()` if needed
4. Follow pattern: defer interaction, process, send response

### Modifying Content Sources

**Add RSS feed:** Edit `RSS_FEEDS` dict in `scraper/news_scraper.py`
```python
"Source Name": {
    "url": "https://example.com/feed",
    "date_format": "rfc822"
}
```

**Add YouTube channel:** Edit `YOUTUBE_CHANNELS` dict in `scraper/content_scheduler.py`
```python
"Channel Name": "CHANNEL_ID_HERE"
```

### Working with Image Generation

Parse user flags with `ImageGenerator.parse_flags()` which returns clean prompt and `ImageConfig` object. Available aspect ratios: square (1:1), wide (16:9), tall (9:16), portrait (3:4), landscape (4:3), ultrawide (21:9).

## Code Conventions

- Async functions for all I/O operations
- Type hints on function signatures
- Docstrings with Location/Summary/Used by headers
- Logging via module-level logger: `logger = logging.getLogger(__name__)`
- Discord embeds for formatted responses
- Command names use lowercase (e.g., `/prof`, `/image`)

## Working Memory
<!-- Auto-managed by pact-memory agent. Last 5 memories shown. -->

### MEM-002: Main.py Refactoring (2026-01-29)

**Context**: Refactored main.py from 692 lines to 428 lines by extracting code into modules.

**Changes**:
- Created `commands.py` (187 lines) - All slash command handlers
- Created `gallery.py` (123 lines) - Forum gallery posting
- Created `utils/` package (252 lines) - Constants, decorators, text formatting

**Key Fix**: Gallery posting wasn't working because `ForumChannel.create_thread()` requires `content` parameter even though docs say optional. Added `content=prompt` to fix.

**Lessons Learned**:
1. Always include `content` parameter when calling `ForumChannel.create_thread()`
2. Don't push partial refactors - the bot crashed when main.py imported from utils/ but utils/ wasn't committed
3. `gemini-2.5-flash-image` only supports `aspect_ratio`, not `image_size` parameter

---

### MEM-001: Peer Review & Codebase Refactor (2026-01-28)

**Branch**: `refactor/codebase-review-fixes` | **PR**: [#1](https://github.com/ProfSynapse/discordbot/pull/1)

**Context**: Full codebase peer review of the Discord bot was completed. Three parallel reviewer agents (architect, test engineer, backend coder) reviewed all source files and consolidated 29 findings: 7 Blocking, 14 Minor, 8 Future. User approved ALL items including "Address now" for all Future items. Implementation was executed in 3 waves organized by file ownership to prevent conflicts among parallel agents.

**Key Decisions**:
- aiohttp session uses lazy creation + no-op `__aexit__` + explicit `close()` pattern
- `asyncio.Semaphore(5)` replaces `Lock` for API concurrency control
- SQLite `seen_content` table consolidates `seen_videos.json` + in-memory `posted_urls`
- Health check uses `aiohttp.web` on port 8080 (configurable via `HEALTH_CHECK_PORT`)

**Lessons Learned**:
1. `config.py` executes `BotConfig.from_env()` at module import time, making it hard to test modules that import from it
2. Wave-based organization by file ownership is effective for parallel agent dispatch without merge conflicts
3. The singleton pattern for `config` and `api_client` creates import-time coupling that complicates testing
