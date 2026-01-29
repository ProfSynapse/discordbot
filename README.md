# DiscordBot with GPT Trainer API & AI Image Generation

A Discord bot that integrates with the [GPT Trainer API](https://guide.gpt-trainer.com/api-key) for conversational AI and Google's Gemini for AI image generation. Features optional automated content scheduling that scrapes AI news and monitors YouTube channels.

## Features

- **Chat Command (`/prof`):** Conversational AI powered by GPT Trainer with your custom knowledge base
- **Image Generation (`/image`):** Generate images using Google's Gemini model with aspect ratio options
- **Session Management:** Per-user conversation history with `/reset` and `/sessioninfo` commands
- **Gallery Auto-Post:** Generated images automatically posted to a forum channel (optional)
- **Automated Content Scheduling** (Optional):
  - News scraper: Posts AI news articles to a designated channel
  - YouTube monitor: Tracks AI-related YouTube channels and posts new videos
  - All content automatically added to your GPT Trainer knowledge base

## Prerequisites

* **Python 3.10+** - [Download](https://www.python.org/downloads/)
* **Discord Bot Token** - [Discord Developer Portal](https://discord.com/developers/applications)
* **GPT Trainer API Token & Chatbot UUID** - [GPT Trainer](https://gpt-trainer.com/)
* **Google API Key** - [Google AI Studio](https://aistudio.google.com/app/apikey)

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/ProfSynapse/discordbot.git
cd discordbot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file:

```env
# Required
DISCORD_TOKEN=your-discord-bot-token
GPT_TRAINER_TOKEN=your-gpt-trainer-api-token
CHATBOT_UUID=your-gpt-trainer-chatbot-uuid
GOOGLE_API_KEY=your-google-api-key

# Optional - Image Gallery (auto-post generated images to a forum channel)
IMAGE_GALLERY_CHANNEL_ID=your-forum-channel-id

# Optional - Content Scheduling (news + YouTube)
CONTENT_CHANNEL_ID=your-discord-channel-id
YOUTUBE_API_KEY=your-youtube-api-key
```

### 3. Run

```bash
python main.py
```

## Commands

### `/prof <prompt>`
Chat with the AI. Uses your GPT Trainer knowledge base for context-aware responses.

```
/prof What are the latest developments in AI?
```

### `/image <prompt> [flags]`
Generate images using Google's Gemini model.

**Aspect Ratio Flags:**
- `--square` (default, 1:1)
- `--wide` (16:9)
- `--tall` (9:16)
- `--portrait` (3:4)
- `--landscape` (4:3)
- `--ultrawide` (21:9)
- Also: `--2:3`, `--3:2`, `--4:5`, `--5:4`

**Examples:**
```
/image a cat reading a book
/image cyberpunk cityscape --wide
/image portrait of a robot --portrait
/image panoramic mountain view --ultrawide
```

**Note:** 60-second cooldown per user.

### `/reset`
Clear your conversation history to start fresh.

### `/sessioninfo`
View your current session details (session ID, message count, age).

## Project Structure

```
discordbot/
├── main.py              # Bot initialization and core DiscordBot class
├── commands.py          # Slash command handlers (/prof, /image, /reset, /sessioninfo)
├── gallery.py           # Forum gallery auto-posting
├── api_client.py        # GPT Trainer API client
├── image_generator.py   # Google Gemini image generation
├── session_manager.py   # Per-user session persistence
├── config.py            # Environment configuration
├── citation_handler.py  # Citation link processing
├── health_check.py      # HTTP health endpoint for Railway/Docker
├── utils/
│   ├── constants.py     # Shared constants
│   ├── decorators.py    # Error handling decorators
│   └── text_formatting.py  # Message splitting and formatting
└── scraper/
    ├── content_scheduler.py  # News + YouTube scheduling
    ├── news_scraper.py       # RSS feed scraping
    └── content_scraper.py    # Article content extraction
```

## Optional Features

### Image Gallery Auto-Post

Set `IMAGE_GALLERY_CHANNEL_ID` to a Discord **forum channel** ID. Generated images will automatically be posted as new forum threads with the prompt as the title.

### Content Scheduling

Set `CONTENT_CHANNEL_ID` and `YOUTUBE_API_KEY` to enable automated content posting.

**Pre-configured Sources:**

| News (RSS Feeds) | YouTube Channels |
|------------------|------------------|
| TechCrunch | AIExplained |
| VentureBeat | OpenAI |
| The Verge (AI) | Google DeepMind |
| MIT Tech Review | Anthropic |
| Wired (AI) | SynapticLabs |
| ArXiv AI papers | GodaGo |
| Various Substacks | WesRoth |

**Customize sources:**
- Edit `scraper/news_scraper.py` → `RSS_FEEDS` dict
- Edit `scraper/content_scheduler.py` → `YOUTUBE_CHANNELS` dict

All posted content is automatically uploaded to your GPT Trainer knowledge base.

## Deployment

### Railway (Recommended)

1. Connect your GitHub repo to [Railway](https://railway.app/)
2. Add environment variables in the Variables tab
3. Deploy

See [RAILWAY_SETUP.md](RAILWAY_SETUP.md) for detailed instructions.

### Docker

```bash
docker build -t discordbot .
docker run -d --env-file .env discordbot
```

## Testing

```bash
# Configuration tests (free, no API calls)
python test_bot.py

# API integration tests (makes real API calls)
python test_apis.py
```

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `GPT_TRAINER_TOKEN` | Yes | GPT Trainer API token |
| `CHATBOT_UUID` | Yes | GPT Trainer chatbot UUID |
| `GOOGLE_API_KEY` | Yes | Google API key for Gemini |
| `IMAGE_GALLERY_CHANNEL_ID` | No | Forum channel for image gallery |
| `CONTENT_CHANNEL_ID` | No | Channel for news/YouTube posts |
| `YOUTUBE_API_KEY` | No | YouTube Data API key |
| `SESSION_DB_PATH` | No | SQLite path (default: `/data/sessions.db`) |
| `LOG_LEVEL` | No | Logging level (default: `INFO`) |

## Contributing

Contributions welcome! Open an issue or submit a pull request.

## License

MIT License
