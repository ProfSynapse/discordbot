"""
scraper/content_scraper.py

Scrapes the text content of a web article given its URL.  Uses aiohttp for async HTTP
fetching and BeautifulSoup for HTML parsing.  Retries with exponential backoff on
transient failures.

Used by:
  - scraper/content_scheduler.py (indirectly, for article content extraction)
"""

import logging
from typing import Optional
import re
import aiohttp
from bs4 import BeautifulSoup
import asyncio

logger = logging.getLogger(__name__)


async def scrape_article_content(url: str, max_retries: int = 3) -> Optional[str]:
    """
    Scrapes article content using aiohttp and BeautifulSoup.
    Returns the main article text content.

    M8 fix: the aiohttp session is created once outside the retry loop so that
    retries reuse the same TCP connection pool instead of opening a new session
    on every attempt.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # M8 fix: session created outside retry loop to avoid per-retry overhead
    async with aiohttp.ClientSession(headers=headers) as session:
        for attempt in range(max_retries):
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise aiohttp.ClientError(f"HTTP {response.status}")

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Remove unwanted elements
                    for unwanted in soup.find_all(['script', 'style', 'nav', 'header', 'footer']):
                        unwanted.decompose()

                    # Try different content selectors
                    content = None
                    selectors = [
                        'article',
                        '[role="article"]',
                        '.article-content',
                        '.post-content',
                        '.entry-content',
                        'main',
                        '#content',
                        '.content'
                    ]

                    for selector in selectors:
                        element = soup.select_one(selector)
                        if element:
                            content = element.get_text()
                            break

                    # Fallback to body if no content found
                    if not content and soup.body:
                        content = soup.body.get_text()

                    if content:
                        # Clean up the content
                        content = re.sub(r'\s+', ' ', content).strip()
                        content = re.sub(r'Share\s*this[\s\S]*$', '', content)
                        content = re.sub(r'Advertisement\s*', '', content, flags=re.IGNORECASE)
                        # Remove email addresses
                        content = re.sub(r'\S+@\S+\s?', '', content)
                        # Remove URLs
                        content = re.sub(r'http\S+\s?', '', content)
                        # Clean up multiple spaces and newlines
                        content = re.sub(r'\n\s*\n', '\n\n', content)
                        return content.strip()

                    return None

            except Exception as e:
                logger.error(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                if attempt == max_retries - 1:
                    logger.error("All retry attempts failed")
                    return None
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                continue

    return None
