# DiscordBot with GPT Trainer API & Google Imagen 4

This Discord bot integrates with the [GPT Trainer API](https://guide.gpt-trainer.com/api-key) to provide interactive conversations and generate responses based on user prompts with an uploaded knowledge base and capabilities for a multi-agent system. It also features AI image generation powered by Google's Imagen 4 models.

## Features

- **Chat Command:** Interact with the bot using the `/prof` command followed by a prompt (this can easily be changed in the code, by replacing wherever it says "prof" with whatever you want)
- **AI Image Generation:** Generate stunning images using the `/image` command with Google's Imagen 4
  - Three quality tiers: `--fast`, `--standard`, `--ultra`
  - Multiple size options from 256x256 up to 4K (4096x4096)
  - Portrait and landscape orientations
- The bot generates responses using the GPT Trainer API based on your uploaded knowledge sources
- Supports handling long responses by splitting them into multiple messages
- Implements basic rate limiting to avoid excessive API requests
- **Automated Content Scheduling** (Optional):
  - News scraper: Automatically posts AI news articles to a designated channel
  - YouTube monitor: Tracks AI-related YouTube channels and posts new videos
  - **Smart Knowledge Base**: All posted content is automatically added to your GPT Trainer chatbot
  - Makes your `/prof` command smarter with each article and video
  - Monitors channels like AIExplained, OpenAI, DeepMind, Anthropic, and more

## Prerequisites

* **Python 3.x:** 
    * **Download:** Ensure you have the latest version from the official Python website: [https://www.python.org/downloads/](https://www.python.org/downloads/)
    * **Installation:** Follow the instructions for your operating system.

* **Discord Bot Token:**
    1. **Discord Developer Portal:** Visit [Dev Portal](https://discord.com/developers/applications)
    2. **Create an Application:** Click "New Application" and give your bot a name.
    3. **Bot Creation:** Navigate to the "Bot" tab and click "Add Bot".
    4. **Token:** Under the bot's profile, you'll see a "Token" section. Click "Copy" to obtain your token. **Keep this token secure!**

* **GPT Trainer API Token and Chatbot UUID:** 
    1. **GPT Trainer Website:**  Visit [https://gpt-trainer.com/](https://gpt-trainer.com/) 
    2. **Account Creation:** Create an account.
    3. **Create a Chatbot:** Follow the GPT Trainer platform's instructions to create a new chatbot project.
    4. **API Token and UUID:** Within your chatbot project settings, you should find your API token and the chatbot's unique UUID.

* **Google API Key (for Image Generation):**
    1. **Google AI Studio:** Visit [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
    2. **Create API Key:** Click "Create API Key" button
    3. **Select/Create Project:** Choose an existing Google Cloud project or create a new one
    4. **Copy Key:** Copy your API key and keep it secure
    
    **Note:** Google AI Studio provides free tier access to Imagen models. For production use with higher limits, you may need to enable billing on your Google Cloud project.  

**Additional Notes**

* **GPT Trainer Documentation:** Refer to the official documentation on the GPT Trainer website for the most up-to-date guidance on setting up your chatbot and obtaining the prerequisites. 
* **Code Examples:** GPT Trainer likely provides code examples or a library to ease the interaction between your Discord bot and their service.

## Getting Started

### 1. Set Up the Discord Bot
1. Go to the Discord Developer Portal: https://discord.com/developers/applications
2. Click on "New Application" and give your bot a name.
3. In the left sidebar, click on "Bot" and then click on "Add Bot".
4. Customize your bot's name and profile picture if desired.
5. Under the "Token" section, click on "Copy" to copy your bot token. Keep this token secure and do not share it with anyone.
6. In the left sidebar, click on "OAuth2" and then click on "URL Generator".
7. Under "Scopes", select "bot".
8. Under "Bot Permissions", select the permissions your bot requires (e.g., "Send Messages", "Read Message History").
9. Copy the generated OAuth2 URL and paste it into your web browser.
10. Select the Discord server you want to add the bot to and click on "Authorize".

### 2. Clone the Repository

1. Install Git on your computer if you haven't already. You can download it from the official website: [https://git-scm.com/downloads](https://git-scm.com/downloads)

2. Open a terminal or command prompt and navigate to the directory where you want to store the project.

3. Run the following command to clone the repository:
   ```
   git clone https://github.com/your-username/your-repo.git
   ```
   Replace `your-username` with your GitHub username and `your-repo` with the name of the repository.

### 3. Set Up the Development Environment

1. Install Visual Studio Code (VS Code) on your computer. You can download it from the official website: [https://code.visualstudio.com/download](https://code.visualstudio.com/download)

2. Open VS Code and go to File -> Open Folder. Navigate to the directory where you cloned the repository and select it.

3. Open a terminal within VS Code by going to Terminal -> New Terminal.

4. Run the following command to create a virtual environment:
   ```
   python -m venv venv
   ```

### 4. Activate the virtual environment:
   - For Windows:
     ```
     venv\Scripts\activate
     ```
   - For macOS and Linux:
     ```
     source venv/bin/activate
     ```

6. Install the required dependencies by running the following command:
   ```
   pip install -r requirements.txt
   ```

### 5. Configure the Bot

1. Create a new file named `.env` in the project directory.

2. Open the `.env` file and add the following lines:
   ```
   # Required for basic bot functionality
   DISCORD_TOKEN=your-discord-bot-token
   GPT_TRAINER_TOKEN=your-gpt-trainer-api-token
   CHATBOT_UUID=your-gpt-trainer-chatbot-uuid
   GOOGLE_API_KEY=your-google-api-key
   
   # Optional: For automated content scheduling (news + YouTube videos)
   CONTENT_CHANNEL_ID=your-discord-channel-id
   YOUTUBE_API_KEY=your-youtube-api-key
   ```
   Replace the placeholder values with your actual tokens, IDs, and keys.

   *The UUID can be found in your chatbot's dashboard in the top left under your Chatbots name.*
   *Get your Google API key from [Google AI Studio](https://aistudio.google.com/app/apikey)*

3. **About Content Scheduling (Optional):**
   - `CONTENT_CHANNEL_ID`: Discord channel **ID** where both AI news and YouTube videos will be automatically posted
     - Right-click a Discord channel → Copy Channel ID (you need Developer Mode enabled in Discord settings)
     - Both news articles and YouTube videos will post to this same channel
   - `YOUTUBE_API_KEY`: Required for YouTube monitoring (get from [Google Cloud Console](https://console.cloud.google.com/))
   - If you don't want automated content, you can skip these variables (the bot will still work for chat and image generation)

4. **What Gets Posted (Pre-configured Sources):**
   
   **News Sources (in `scraper/news_scraper.py`):**
   - TechCrunch
   - VentureBeat
   - The Verge (AI section)
   - MIT Tech Review (AI)
   - Wired (AI)
   - ArXiv AI papers
   - Substack: Professor Synapse, Gary Marcus, One Useful Thing, Prompthub, Astral Codex
   
   **YouTube Channels Monitored (in `scraper/content_scheduler.py`):**
   - AIExplained
   - OpenAI
   - Google DeepMind
   - Anthropic
   - SynapticLabs
   - GodaGo
   - WesRoth
   
   *You can edit these files to add/remove sources and channels!*

### 6. Test Your Configuration

Before running the bot, test that everything is configured correctly:

#### Configuration Tests (Recommended - Free)
```bash
python test_bot.py
```

This will check:
- Environment file and required variables
- Python package dependencies
- Google API connectivity
- GPT Trainer API connectivity
- Configuration loading

#### API Integration Tests (Optional - Makes Real API Calls)
```bash
python test_apis.py
```

**⚠️ WARNING: This makes real API calls and may incur costs!**

These tests validate actual functionality:
- GPT Trainer chat and knowledge base uploads
- Google Imagen image generation (all 3 models)
- Different image sizes and formats
- Content scraping functionality

The script will ask for confirmation before each test. To skip confirmations:
```bash
python test_apis.py --yes
```

If all configuration tests pass ✓, you're ready to run the bot!

### 7. Run the Bot

1. In the VS Code terminal, run the following command to start the bot:
   ```
   python main.py
   ```

2. The bot should now be running and connected to your Discord server.

## Hosting the Bot

If you want to host the bot continuously without running it on your local machine, you can use platforms like Replit or Railway.

**Recommended: Railway** - See [RAILWAY_SETUP.md](RAILWAY_SETUP.md) for a complete Railway deployment guide.

### Hosting on Replit

1. Sign up for a free account on [Replit](https://replit.com/).(Note you will need to purchase an account to keep it continuosly running.

2. Click on the "+" button to create a new repl.

3. Select "Python" as the language and give your repl a name.

4. In the Replit editor, upload the files from your local project directory (`main.py`, `discord_api.py`).

5. Open the "Secrets" tab (bottom left in the list) and add in all of your keys (Bot token, GPT Trainer API, UUID for your chatbot)

6. Click on the "Run" button to start the bot.

7. Keep the Replit tab open to keep the bot running continuously.

### Hosting on Railway

1. Sign up for a free account on [Railway](https://railway.app/).

2. Create a new project and select "Deploy from GitHub".

3. Connect your GitHub account and select the repository containing your bot code.

4. Configure the environment variables in the Railway dashboard:
   - `DISCORD_TOKEN`
   - `GPT_TRAINER_TOKEN`
   - `CHATBOT_UUID`
   - `GOOGLE_API_KEY` (Get from [Google AI Studio](https://aistudio.google.com/app/apikey))
   - `NEWS_CHANNEL_ID`
   - `YOUTUBE_CHANNEL_ID`
   - `YOUTUBE_API_KEY`

5. Click on "Deploy" to deploy your bot.

6. Railway will automatically keep your bot running continuously.

**Note:** Make sure to set all environment variables before deploying. Railway makes it easy - just go to the Variables tab and add each key-value pair.

## Usage

### Chat Command

1. Invite the bot to your Discord server using the OAuth2 URL generated in the Discord Developer Portal.

2. Use the `/prof` command followed by a prompt to interact with the bot. For example:
   ```
   /prof What is the meaning of life?
   ```

3. The bot will generate a response based on the provided prompt and send it back to the Discord channel.

### Image Generation Command

Use the `/image` command to generate AI images with Google's Imagen 4:

#### Basic Usage
```
/image a dog reading a newspaper
```

#### Model Selection (Quality Tiers)
- `--fast` - Quick generation (default) - **Note: Uses fixed default size**
- `--standard` - Balanced speed and quality - Supports custom sizes
- `--ultra` - Highest quality, slower generation - Supports custom sizes

```
/image a sunset over mountains --ultra
/image cyberpunk city at night --fast
/image portrait of a robot --standard
```

#### Size Options (Standard and Ultra models only)
- `--square` or `--1k` - 1024x1024 (default)
- `--2k` or `--large` - 2048x2048 (higher resolution)

**Note:** The fast model does not support custom sizes and uses a fixed default.

```
/image detailed fantasy castle --standard --2k
/image modern architecture --ultra --large
/image mountain landscape --landscape --ultra
/image modern architecture --ultra --large
/image quick concept sketch --fast
```

#### Format Options
- `--png` - PNG format (default, best quality)
- `--jpeg` or `--jpg` - JPEG format (smaller file size)

```
/image scenic landscape --standard --2k --jpeg
```

#### Combined Examples
```
# High quality 2K image in PNG (Standard model)
/image photorealistic portrait of an owl --standard --2k --png

# Ultra quality with large size
/image detailed fantasy landscape --ultra --large --png

# Fast generation (fixed size)
/image quick character sketch --fast --jpeg
````
```

#### With Format Flags
- `--png` - PNG format (default, best quality)
- `--jpeg` or `--jpg` - JPEG format (smaller file size)

```
/image scenic view --landscape --jpeg
```

#### Combined Examples
```
# High quality 4K image in PNG
/image photorealistic portrait of an owl --ultra --square-xl --png

# Fast 2K landscape in JPEG
/image sunset over ocean --fast --square-large --jpeg

# Standard quality portrait
/image detailed character design --standard --portrait
```

**Note:** The image command has a 60-second cooldown per user to manage API costs.

For detailed information about image generation, see [IMAGEN_MIGRATION.md](IMAGEN_MIGRATION.md).

### Automated Content Scheduling (Optional Feature)

If you've configured the optional content scheduling variables, the bot will automatically post content to your designated Discord channel.

**What you need to set up:**
1. Create a Discord channel (e.g., `#ai-updates`)
2. Get the channel ID (right-click → Copy Channel ID - requires Developer Mode)
3. Add the ID to your environment variables as `CONTENT_CHANNEL_ID`
4. Get a YouTube API key and set it as `YOUTUBE_API_KEY`

#### What Gets Posted to Your Channel
The bot posts both news articles and YouTube videos to the **same channel**, and **automatically adds all content to your GPT Trainer knowledge base**:

**News Articles** (from Pre-configured RSS Feeds):
- **Tech News**: TechCrunch, VentureBeat, The Verge (AI), Wired (AI)
- **Research**: MIT Tech Review (AI), ArXiv AI papers
- **Substacks**: Professor Synapse, Gary Marcus, One Useful Thing, Prompthub, Astral Codex

**YouTube Videos** (from Monitored Channels):
- AIExplained, OpenAI, Google DeepMind, Anthropic
- SynapticLabs, GodaGo, WesRoth

**🤖 Automatic Knowledge Base Integration:**
Every article and video posted is automatically uploaded to your GPT Trainer chatbot's knowledge base. This means:
- Your `/prof` command becomes smarter with each post
- The bot can answer questions about recent AI news and videos
- No manual saving required - everything is indexed automatically
- Your chatbot stays up-to-date with the latest AI developments

**Want different sources?** Edit the source files:
- News feeds: `scraper/news_scraper.py` → `RSS_FEEDS` dictionary
- YouTube channels: `scraper/content_scheduler.py` → `YOUTUBE_CHANNELS` dictionary

#### How to Customize Sources

**Add a new RSS feed:**
```python
# In scraper/news_scraper.py, add to RSS_FEEDS:
"Your Source Name": {
    "url": "https://example.com/feed",
    "date_format": "rfc822"
}
```

**Add a new YouTube channel:**
```python
# In scraper/content_scheduler.py, add to YOUTUBE_CHANNELS:
"Channel Name": "CHANNEL_ID_HERE"
```

To find a YouTube channel ID: Go to the channel → View Page Source → Search for "channelId"


## Roadmap
1. ~~Add ability to find and summarize shared links~~ ✅ (Completed)
2. ~~Integrate AI image generation~~ ✅ (Completed - Google Imagen 4)
3. Improve image generation with style presets
4. Add image editing capabilities

## Additional Documentation

- **[RAILWAY_SETUP.md](RAILWAY_SETUP.md)** - Complete guide for deploying to Railway with environment variables
- **[IMAGEN_MIGRATION.md](IMAGEN_MIGRATION.md)** - Complete guide to Google Imagen 4 integration, setup, and troubleshooting
- **[MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md)** - Quick reference for the OpenAI to Google Imagen migration

## Contributing

Contributions are welcome! If you find any issues or have suggestions for improvements, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
