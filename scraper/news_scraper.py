import logging
import asyncio
from typing import List, Dict
import aiohttp
import feedparser
from datetime import datetime
import pytz
from time import mktime
from email.utils import parsedate_to_datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SCRAPED_URLS = set()

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
        if format_type == "rfc822":
            return parsedate_to_datetime(date_str)
        elif format_type == "arxiv":
            # Handle both arXiv formats
            try:
                # Try ISO format first
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.UTC)
            except ValueError:
                # Try RFC822 format as fallback
                return parsedate_to_datetime(date_str)
        else:
            # Fallback to RFC822
            return parsedate_to_datetime(date_str)
    except Exception as e:
        logging.error(f"Error parsing date {date_str}: {e}")
        # Return current time instead of min time for better sorting
        return datetime.now(pytz.UTC)

async def fetch_feed(session: aiohttp.ClientSession, name: str, feed_info: Dict) -> List[Dict]:
    try:
        logger.info(f"Fetching {name} RSS feed")
        async with session.get(feed_info["url"]) as response:
            content = await response.text()
            feed = feedparser.parse(content)
            
            articles = []
            for entry in feed.entries[:20]:  # Check last 20 entries
                try:
                    # Extract image URL from media content or enclosures
                    image_url = None
                    if 'media_content' in entry:
                        media_urls = [m['url'] for m in entry.media_content if 'url' in m]
                        if media_urls:
                            image_url = media_urls[0]
                    elif 'enclosures' in entry:
                        image_urls = [e['href'] for e in entry.enclosures if 'href' in e and e.get('type', '').startswith('image/')]
                        if image_urls:
                            image_url = image_urls[0]

                    # Extract and clean summary
                    summary = entry.get('summary', '')
                    if not summary and 'description' in entry:
                        summary = entry['description']
                        
                    # Clean the summary
                    summary = summary.replace('<p>', '').replace('</p>', '\n').strip()

                    # Check if article is AI-related
                    if any(keyword in entry.title.lower() or keyword in summary.lower() for keyword in AI_KEYWORDS):
                        articles.append({
                            "title": entry.title,
                            "url": entry.link,
                            "summary": summary,
                            "source": name,
                            "published": parse_date(entry.get('published', entry.get('updated', ''))),
                            "image_url": image_url
                        })
                        logger.info(f"Found AI-related article from {name}: {entry.title}")
                except Exception as e:
                    logger.error(f"Error processing entry from {name}: {e}")
                    continue
            
            return articles[:3]  # Return up to 3 matching articles per source
            
    except Exception as e:
        logger.error(f"Error fetching {name} feed: {e}", exc_info=True)
        return []

def filter_new_articles(articles: List[Dict]) -> List[Dict]:
    return [a for a in articles if a["url"] not in SCRAPED_URLS and not SCRAPED_URLS.add(a["url"])]

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
        all_articles.sort(
            key=lambda x: datetime.fromisoformat(x['published']),
            reverse=True
        )
        
        filtered_articles = filter_new_articles(all_articles)
        logger.info(f"Total articles: {len(all_articles)}, After filtering: {len(filtered_articles)}")
        return filtered_articles
        
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