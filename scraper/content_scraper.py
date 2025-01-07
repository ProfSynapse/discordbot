import logging
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional, Dict
import re

logger = logging.getLogger(__name__)

async def scrape_article_content(url: str) -> Optional[Dict[str, str]]:
    """
    Scrape article content using basic aiohttp and BeautifulSoup.
    Returns dict with 'title' and 'content' if successful, None if failed.
    """
    try:
        async with aiohttp.ClientSession() as session:
            logger.info(f"Fetching content from: {url}")
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch URL: {url}, status: {response.status}")
                    return None
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Get title
                title = soup.title.string if soup.title else ""
                
                # Try to get main content
                # Remove script and style elements
                for script in soup(["script", "style", "nav", "header", "footer"]):
                    script.decompose()
                
                # Get text
                content = soup.get_text()
                
                # Clean up text
                lines = (line.strip() for line in content.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                content = '\n'.join(chunk for chunk in chunks if chunk)
                
                # Remove excessive newlines
                content = re.sub(r'\n\s*\n', '\n\n', content)
                
                return {
                    'title': title.strip(),
                    'content': content.strip()
                }
                
    except Exception as e:
        logger.error(f"Error scraping article content: {e}", exc_info=True)
        return None
