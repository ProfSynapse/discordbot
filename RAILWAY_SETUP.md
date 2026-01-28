# Railway Deployment Guide

## Quick Setup for Railway

### Step 1: Get Your API Keys

1. **Discord Bot Token**
   - [Discord Developer Portal](https://discord.com/developers/applications)

2. **GPT Trainer**
   - Token and UUID from [GPT Trainer](https://gpt-trainer.com/)

3. **Google API Key** 
   - Get it from [Google AI Studio](https://aistudio.google.com/app/apikey)
   - Click "Create API Key"
   - Select/create a project
   - Copy your key

4. **YouTube API Key** (optional)
   - [Google Cloud Console](https://console.cloud.google.com/)

### Step 2: Deploy to Railway

1. **Fork/Clone This Repository**
   ```bash
   git clone https://github.com/ProfSynapse/discordbot.git
   ```

2. **Go to Railway**
   - Visit [railway.app](https://railway.app/)
   - Sign up or log in
   - Click "New Project"

3. **Deploy from GitHub**
   - Click "Deploy from GitHub repo"
   - Select your repository
   - Railway will automatically detect it's a Python project

### Step 3: Configure Environment Variables

In Railway, go to your project → Variables tab and add:

#### Required Variables (Core Functionality)

| Variable | Description | Required |
|----------|-------------|----------|
| `DISCORD_TOKEN` | Your Discord bot token | ✅ Yes |
| `GPT_TRAINER_TOKEN` | GPT Trainer API token | ✅ Yes |
| `CHATBOT_UUID` | Your chatbot's UUID | ✅ Yes |
| `GOOGLE_API_KEY` | Google API key for image generation | ✅ Yes |

#### Optional Variables (Automated Content Scheduling)

| Variable | Description | Required |
|----------|-------------|----------|
| `CONTENT_CHANNEL_ID` | Discord channel ID for all automated content (news + videos) | ❌ Optional |
| `YOUTUBE_API_KEY` | YouTube API key for video monitoring | ❌ Optional |
| `LOG_LEVEL` | Logging level (INFO, DEBUG, etc.) | ❌ Optional |

**Note:** The bot will work for `/prof` chat and `/image` generation without the optional variables. 

**About Content Scheduling:**
- `CONTENT_CHANNEL_ID` is a Discord channel ID (right-click channel → Copy Channel ID)
- Both news articles AND YouTube videos will post to this **same channel**
- **All content is automatically uploaded to your GPT Trainer knowledge base**
- This makes your `/prof` chatbot smarter with each post - it learns from every article and video!
- Default news sources: TechCrunch, VentureBeat, The Verge, MIT Tech Review, Wired, ArXiv, various Substacks
- Default YouTube channels: AIExplained, OpenAI, DeepMind, Anthropic, and more
- To customize sources, edit `scraper/news_scraper.py` and `scraper/content_scheduler.py`

### Step 4: Deploy!

Railway will automatically:
- Install dependencies from `requirements.txt`
- Start your bot using `main.py`
- Keep it running 24/7
- Restart it if it crashes

### Testing Your Bot

Once deployed, test both commands in Discord:

```bash
# Test chat
/prof Hello!

# Test image generation
/image a cute dog --fast
```

## Cost Management

### Free Tiers
- **Railway**: $5/month free credit (enough for small bots)
- **Google Imagen**: Free tier with usage limits
- **Discord**: Free
- **GPT Trainer**: Check their pricing

### Tips to Stay Within Limits
1. Use `--fast` model by default (cheaper, faster)
2. Keep the 60-second cooldown on `/image` command
3. Monitor your Railway usage dashboard
4. Watch Google AI Studio quota

### Upgrading

If you exceed free tiers:
- **Railway**: Add a credit card for $5+/month
- **Google**: Enable billing for higher Imagen quotas

## Troubleshooting

### Bot Won't Start
1. Check Railway logs (click on deployment)
2. Verify all required environment variables are set
3. Make sure your Discord token is valid

### Image Generation Fails
```
Error: Invalid API key
```
- Check `GOOGLE_API_KEY` is set correctly
- Get a new key from [Google AI Studio](https://aistudio.google.com/app/apikey)

### "Module not found" Error
- Railway should auto-install from `requirements.txt`
- Check the build logs to see if installation succeeded

### Bot Goes Offline
- Check Railway dashboard for errors
- View logs for detailed error messages
- Restart the deployment if needed

## Monitoring

### Railway Dashboard
- **Deployments**: See all deployments and their status
- **Metrics**: CPU, memory, network usage
- **Logs**: Real-time logs from your bot
- **Usage**: Track your monthly usage

### Set Up Alerts
1. Join your Discord server
2. Watch for bot going offline
3. Check Railway email notifications

## Updating Your Bot

### Option 1: Auto-Deploy (Recommended)
1. Push changes to your GitHub repo
2. Railway auto-deploys on every push to main branch

### Option 2: Manual Deploy
1. Go to Railway dashboard
2. Click "Deploy" on latest commit
3. Wait for deployment to complete

## Support

- **Railway Issues**: [Railway Discord](https://discord.gg/railway)
- **Google API Issues**: [Google AI Studio](https://aistudio.google.com/)
- **Bot Issues**: Check logs in Railway dashboard
