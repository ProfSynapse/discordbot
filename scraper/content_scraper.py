import logging
from typing import Optional
import re
from pyppeteer import launch

logger = logging.getLogger(__name__)

async def scrape_article_content(url: str) -> Optional[str]:
    """
    Scrapes article content using Pyppeteer.
    Returns the main article text content.
    """
    try:
        browser = await launch(headless=True)
        page = await browser.newPage()
        
        # Set timeout to 30 seconds
        await page.setDefaultNavigationTimeout(30000)
        
        # Navigate to the page
        await page.goto(url)
        
        # Wait for content to load
        await page.waitForSelector('article, [role="article"], .article, .post-content, .entry-content', 
                                 timeout=5000)
        
        # Try different selectors for article content
        content = await page.evaluate('''
            () => {
                // Common article content selectors
                const selectors = [
                    'article', 
                    '[role="article"]',
                    '.article-content',
                    '.post-content',
                    '.entry-content',
                    'main'
                ];
                
                for (const selector of selectors) {
                    const element = document.querySelector(selector);
                    if (element) {
                        // Remove unwanted elements
                        const unwanted = element.querySelectorAll(
                            'script, style, nav, header, footer, .social-share, .advertisement'
                        );
                        unwanted.forEach(el => el.remove());
                        
                        return element.textContent;
                    }
                }
                
                // Fallback: get body content
                return document.body.textContent;
            }
        ''')
        
        await browser.close()
        
        if content:
            # Clean up the content
            content = re.sub(r'\s+', ' ', content).strip()  # Remove extra whitespace
            content = re.sub(r'Share\s*this[\s\S]*$', '', content)  # Remove sharing section
            return content
            
        return None
        
    except Exception as e:
        logger.error(f"Error scraping article content: {e}")
        return None
