import logging
from pyppeteer import launch
import asyncio
from typing import Optional, Dict

logger = logging.getLogger(__name__)

async def scrape_article_content(url: str) -> Optional[Dict[str, str]]:
    """Scrape article content using pyppeteer."""
    try:
        browser = await launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        try:
            page = await browser.newPage()
            await page.goto(url, {'waitUntil': 'networkidle0'})
            
            # Extract content using JavaScript
            content = await page.evaluate('''() => {
                // Remove unwanted elements
                const removeSelectors = [
                    'nav', 'header', 'footer', 'script', 'style',
                    'iframe', 'advertisement', '.ad', '.ads', '.social-share',
                    '.related-articles', '.comments'
                ];
                removeSelectors.forEach(selector => {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                });
                
                // Get title
                const title = document.querySelector('h1')?.textContent?.trim() || 
                            document.title.trim();
                
                // Get main content
                const article = document.querySelector('article') || document.body;
                const paragraphs = Array.from(article.querySelectorAll('p'))
                    .map(p => p.textContent.trim())
                    .filter(text => text.length > 50);  // Filter out short paragraphs
                
                return {
                    title: title,
                    content: paragraphs.join('\\n\\n')
                };
            }''')
            
            return content
            
        finally:
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping article content: {e}")
        return None
