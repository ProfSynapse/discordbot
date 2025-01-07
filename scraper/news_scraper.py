import logging
import asyncio
from typing import List, Dict
import aiohttp
import feedparser
from datetime import datetime, timedelta
import pytz
from time import mktime
from email.utils import parsedate_to_datetime
import re
from markdownify import markdownify as md

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Removed SCRAPED_URLS = set()

# Update RSS_FEEDS with format info
RSS_FEEDS = {
    "TechCrunch": {
        "url": "https://techcrunch.com/feed/",
        "date_format": "rfc822"  # Standard RSS date format
    },
    "VentureBeat": {
        "url": "https://feeds.feedburner.com/venturebeat/SZYF",
        "date_format": "rfc822"
    },
    "The Verge": {
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "date_format": "rfc822"
    },
    "MIT Tech Review": {
        "url": "https://www.technologyreview.com/feed/artificial-intelligence/rss/",
        "date_format": "rfc822"
    },
    "ArXiv AI": {
        "url": "http://export.arxiv.org/rss/cs.AI",
        "date_format": "arxiv"  # Special handling for arXiv
    },
    "Meditations on Alignment": {
        "url": "https://professorsynapse.substack.com/",
        "date_format": "rfc822"
    },
    "Gary Marcus": {
        "url": "https://garymarcus.substack.com/feed",
        "date_format": "rfc822"
    },
    "One Useful Thing": {
        "url": "https://oneusefulthing.substack.com/feed",
        "date_format": "rfc822"
    },
    "Prompthub": {
        "url": "https://prompthub.substack.com/feed",
        "date_format": "rfc822"
    },
        "Astral Codex": {
        "url": "https://astralcodexten.substack.com/feed",
        "date_format": "rfc822"
    }
}

# Keywords to filter AI-related content
AI_KEYWORDS = [
    'artificial intelligence', 'machine learning', 'deep learning', 
    'neural network', 'ai ', 'large language model',
    'llm', 'gpt', 'chatgpt', 'transformer', 'openai', 'anthropic',
    'gemini', 'claude', 'mistral', 'reinforcement learning', 'ethics', 'reasoning'
]

def parse_date(date_str: str, format_type: str) -> datetime:
    """Parse date string based on source format."""
    try:
        if not date_str:
            return datetime.now(pytz.UTC)
            
        # First try parsing as ISO format with various cleanup attempts
        try:
            # Clean up timezone info
            date_str = date_str.replace('Z', '+00:00').replace('.000', '')
            
            # Handle various ISO formats
            if 'T' in date_str:
                # Try direct fromisoformat
                try:
                    return datetime.fromisoformat(date_str)
                except ValueError:
                    # Try removing timezone and add UTC
                    clean_date = re.sub(r'[+-]\d{2}:?\d{2}$', '', date_str)
                    return datetime.fromisoformat(clean_date).replace(tzinfo=pytz.UTC)
        except ValueError:
            pass

        # Try RFC822 (most RSS feeds use this)
        try:
            return parsedate_to_datetime(date_str)
        except (TypeError, ValueError):
            pass

        # Fallback to common formats
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=pytz.UTC)
            except ValueError:
                continue

        logger.error(f"Could not parse date: {date_str}")
        return datetime.now(pytz.UTC)
        
    except Exception as e:
        logger.error(f"Error parsing date {date_str}: {e}")
        return datetime.now(pytz.UTC)

# Add Substack identification
def is_substack_feed(source: str, url: str) -> bool:
    return 'substack.com' in url.lower() or source in [
        "Meditations on Alignment",
        "Gary Marcus",
        "One Useful Thing",
        "Prompthub",
        "Astral Codex"
    ]

# Fix the keyword error in fetch_feed function
async def fetch_feed(session: aiohttp.ClientSession, name: str, feed_info: Dict) -> List[Dict]:
    try:
        logger.info(f"Fetching {name} RSS feed")
        async with session.get(feed_info["url"]) as response:
            content = await response.text()
            feed = feedparser.parse(content)
            
            articles = []
            is_substack = is_substack_feed(name, feed_info["url"])
            one_day_ago = datetime.now(pytz.UTC) - timedelta(days=1)
            
            logger.debug(f"Processing {len(feed.entries)} entries from {name}")
            
            for entry in feed.entries[:20]:  # Check last 20 entries
                try:
                    # Get the date first - add debug logging
                    raw_date = entry.get('published', entry.get('updated', ''))
                    logger.debug(f"{name} raw date: {raw_date}")
                    
                    date = parse_date(raw_date, feed_info["date_format"])
                    logger.debug(f"{name} parsed date: {date}")

                    # Always apply date filtering
                    if date < one_day_ago:
                        logger.debug(f"Skipping old article from {name}: {entry.title}")
                        continue

                    # For Substacks, skip keyword filtering but keep date filtering
                    if is_substack:
                        logger.debug(f"Found recent Substack article: {entry.title} from {name}")
                        articles.append({
                            "title": entry.title,
                            "url": entry.link,
                            "summary": entry.get('summary', ''),
                            "source": name,
                            "published": date.isoformat(),
                            "image_url": None  # Simplified for debugging
                        })
                        continue

                    # For non-Substacks, apply keyword filtering
                    if any(kw in entry.title.lower() or 
                          kw in entry.get('summary', '').lower() 
                          for kw in AI_KEYWORDS):
                        # Process non-Substack article
                        # ...existing article processing code...
                        pass

                except Exception as e:
                    logger.error(f"Error processing entry from {name}: {e}")
                    continue
            
            if is_substack:
                logger.info(f"Found {len(articles)} articles from Substack {name} in last 24h")
            
            return articles
            
    except Exception as e:
        logger.error(f"Error fetching {name} feed: {e}", exc_info=True)
        return []

# Removed filter_new_articles function

async def scrape_all_sites() -> List[Dict]:
    logger.info("Starting scrape_all_sites")
    all_articles = []
    
    try:
        async with aiohttp.ClientSession() as session:
            tasks = [
                fetch_feed(session, name, feed_info) 
                for name, feed_info in RSS_FEEDS.items()
            ]
            
            logger.info(f"Created {len(tasks)} scraping tasks")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                source = list(RSS_FEEDS.keys())[i]
                if isinstance(result, Exception):
                    logger.error(f"Error scraping {source}: {result}")
                    continue
                    
                logger.info(f"Got {len(result)} articles from {source}")
                all_articles.extend(result)
                
            # Sort by publication date
            try:
                all_articles.sort(
                    key=lambda x: datetime.fromisoformat(x.get('published', datetime.now(pytz.UTC).isoformat())),
                    reverse=True
                )
            except Exception as e:
                logger.error(f"Error sorting articles: {e}")
            
            # Return all_articles directly now:
            return all_articles
            
    except Exception as e:
        logger.error(f"Error in scrape_all_sites: {e}", exc_info=True)
        return []

async def main():
    results = await scrape_all_sites()
    for result in results:
        logger.info(f"Title: {result['title']}\nSource: {result['source']}\n"
                   f"Published: {result['published']}\nURL: {result['url']}\n"
                   f"Summary: {result['summary']}\n")

if __name__ == "__main__":
    asyncio.run(main())