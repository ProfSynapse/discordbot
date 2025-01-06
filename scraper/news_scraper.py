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

# Fix the keyword error in fetch_feed function
async def fetch_feed(session: aiohttp.ClientSession, name: str, feed_info: Dict) -> List[Dict]:
    try:
        logger.info(f"Fetching {name} RSS feed")
        async with session.get(feed_info["url"]) as response:
            content = await response.text()
            feed = feedparser.parse(content)
            
            articles = []
            for entry in feed.entries[:20]:  # Check last 20 entries
                try:
                    # Extract and clean summary
                    summary = entry.get('summary', '')
                    if not summary and 'description' in entry:
                        summary = entry['description']
                    
                    # Convert HTML to Discord-friendly markdown - fixed markdownify params
                    summary = md(
                        summary,
                        heading_style="atx",
                        convert=['b', 'i', 'em', 'strong', 'a', 'img', 'p', 'br', 'ul', 'ol', 'li'],  # Specify all tags to convert
                        escape_asterisks=True,
                        escape_underscores=True
                    )
                    
                    # Clean up the converted markdown
                    summary = (summary
                              .replace('\n\n\n', '\n\n')  # Remove triple newlines
                              .replace('!\[\]', '')        # Remove empty image markers
                              .strip())                    # Remove leading/trailing whitespace
                    
                    # Extract image URL from HTML content
                    image_url = None
                    if '[Image' in summary:
                        # Extract URL from the [Image...] format
                        img_match = re.search(r'src="([^"]+)"', summary)
                        if img_match:
                            image_url = img_match.group(1)
                            # Remove the entire [Image...] text from summary
                            summary = re.sub(r'\[Image[^\]]+\]', '', summary)
                    elif 'media_content' in entry:
                        media_urls = [m['url'] for m in entry.media_content if 'url' in m]
                        if media_urls:
                            image_url = media_urls[0]
                    elif 'enclosures' in entry:
                        image_urls = [e['href'] for e in entry.enclosures 
                                    if 'href' in e and e.get('type', '').startswith('image/')]
                        if image_urls:
                            image_url = image_urls[0]

                    # Clean the summary more thoroughly
                    summary = (summary.replace('<p>', '')
                                     .replace('</p>', '\n')
                                     .replace('<figure>', '')
                                     .replace('</figure>', '')
                                     .replace('<figcaption>', '')
                                     .replace('</figcaption>', '')
                                     .replace('<img', '')
                                     .replace('/>', ''))
                    
                    # Remove HTML IDs
                    summary = re.sub(r'id="[^"]*"', '', summary)
                    # Remove any remaining HTML tags
                    summary = re.sub(r'<[^>]+>', '', summary)
                    # Remove any remaining "Image:" or "Source:" tags
                    summary = re.sub(r'Image:\s*[^\n]+\n?', '', summary)
                    # Fix multiple newlines
                    summary = re.sub(r'\n\s*\n', '\n\n', summary)
                    summary = summary.strip()
                    
                    # Check if article is AI-related
                    if any(kw in entry.title.lower() or kw in summary.lower() 
                          for kw in AI_KEYWORDS):
                        # Parse date with correct format type
                        try:
                            date = parse_date(
                                entry.get('published', entry.get('updated', '')),
                                feed_info["date_format"]
                            )
                            date_str = date.isoformat()
                        except Exception as e:
                            logger.error(f"Date parsing error: {e}")
                            date_str = datetime.now(pytz.UTC).isoformat()
                        
                        if feed_info["date_format"] == "arxiv":
                            # Special handling for arXiv entries
                            try:
                                # Get authors
                                authors = ', '.join([author.get('name', '') for author in entry.get('authors', [])])
                                
                                # Clean and format the summary/abstract
                                summary = entry.get('summary', '').strip()
                                
                                # Remove Announce Type and arXiv ID prefixes
                                summary = re.sub(r'arXiv:\d+\.\d+v\d+\s+Announce Type:\s+\w+\s*', '', summary)
                                summary = re.sub(r'Abstract:\s*', '', summary)
                                
                                # Format date as YYYY-MM-DD
                                formatted_date = date.strftime('%Y-%m-%d')
                                
                                # Create clean formatted summary
                                formatted_summary = f"{summary.strip()}\n\n"  # Abstract first
                                formatted_summary += f"*{authors} - {formatted_date}*"  # Authors and date in italics
                                
                                # Clean up title (remove any arXiv IDs or other prefixes)
                                clean_title = re.sub(r'arXiv:\d+\.\d+v\d+\s*', '', entry.title)
                                clean_title = clean_title.replace('\n', ' ').strip()
                                
                                articles.append({
                                    "title": clean_title,
                                    "url": entry.link,
                                    "summary": formatted_summary,
                                    "source": name,
                                    "published": date_str,
                                    "image_url": image_url
                                })
                            except Exception as e:
                                logger.error(f"Error processing arXiv entry: {e}")
                                continue
                        else:
                            articles.append({
                                "title": entry.title,
                                "url": entry.link,
                                "summary": summary,
                                "source": name,
                                "published": date_str,
                                "image_url": image_url  # Now properly cleaned and verified
                            })
                            logger.info(f"Found AI-related article from {name}: {entry.title}")
                except Exception as e:
                    logger.error(f"Error processing entry from {name}: {e}")
                    continue
            
            return articles  # Return all matching articles
            
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