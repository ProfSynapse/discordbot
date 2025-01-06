import logging
import asyncio
from typing import List, Dict
from pyppeteer import launch
from datetime import datetime, timedelta
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SCRAPED_URLS = set()

# List of common user agents for randomization
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
]

async def create_browser():
    return await launch(
        headless=True,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-gpu'
        ]
    )

async def scrape_axios() -> List[Dict]:
    try:
        logger.info("Starting Axios scrape")
        browser = await create_browser()
        
        try:
            page = await browser.newPage()
            await page.setUserAgent(random.choice(USER_AGENTS))
            await page.setViewport({'width': 1920, 'height': 1080})
            
            # Add random delay to seem more human-like
            await asyncio.sleep(random.uniform(2, 4))
            
            await page.goto('https://www.axios.com/technology', {'waitUntil': 'networkidle0'})
            
            articles = await page.evaluate('''() => {
                const articles = [];
                document.querySelectorAll('article').forEach(article => {
                    const titleEl = article.querySelector('h2, h3');
                    const linkEl = article.querySelector('a');
                    const previewEl = article.querySelector('p');
                    
                    if (titleEl && linkEl && previewEl) {
                        const title = titleEl.textContent.trim();
                        const url = linkEl.href;
                        const preview = previewEl.textContent.trim();
                        
                        if (title.toLowerCase().includes('ai') || 
                            preview.toLowerCase().includes('artificial intelligence') ||
                            preview.toLowerCase().includes('machine learning')) {
                            articles.push({title, url, preview});
                        }
                    }
                });
                return articles;
            }''')
            
            return [
                {
                    "title": article['title'],
                    "url": article['url'],
                    "summary": article['preview'][:200] + "..." if len(article['preview']) > 200 else article['preview'],
                    "source": "Axios"
                }
                for article in articles[:3]  # Limit to 3 articles
            ]
            
        finally:
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping Axios: {e}", exc_info=True)
        return []

async def scrape_techcrunch() -> List[Dict]:
    try:
        logger.info("Starting TechCrunch scrape")
        browser = await create_browser()
        
        try:
            page = await browser.newPage()
            await page.setUserAgent(random.choice(USER_AGENTS))
            await page.setViewport({'width': 1920, 'height': 1080})
            
            await asyncio.sleep(random.uniform(2, 4))
            
            await page.goto('https://techcrunch.com/category/artificial-intelligence/', {
                'waitUntil': 'networkidle0'
            })
            
            articles = await page.evaluate('''() => {
                const articles = [];
                document.querySelectorAll('article').forEach(article => {
                    const titleEl = article.querySelector('h2');
                    const linkEl = article.querySelector('h2 a');
                    const previewEl = article.querySelector('.post-block__content');
                    
                    if (titleEl && linkEl && previewEl) {
                        articles.push({
                            title: titleEl.textContent.trim(),
                            url: linkEl.href,
                            preview: previewEl.textContent.trim()
                        });
                    }
                });
                return articles;
            }''')
            
            return [
                {
                    "title": article['title'],
                    "url": article['url'],
                    "summary": article['preview'][:200] + "..." if len(article['preview']) > 200 else article['preview'],
                    "source": "TechCrunch"
                }
                for article in articles[:3]  # Limit to 3 articles
            ]
            
        finally:
            await browser.close()
            
    except Exception as e:
        logger.error(f"Error scraping TechCrunch: {e}", exc_info=True)
        return []

def filter_new_articles(articles: List[Dict]) -> List[Dict]:
    return [a for a in articles if a["url"] not in SCRAPED_URLS and not SCRAPED_URLS.add(a["url"])]

async def scrape_all_sites() -> List[Dict]:
    scrapers = [scrape_axios, scrape_techcrunch]
    all_articles = []
    
    for scraper in scrapers:
        try:
            articles = await scraper()
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Error in scraper {scraper.__name__}: {e}")
    
    return filter_new_articles(all_articles)

async def main():
    results = await scrape_all_sites()
    for result in results:
        logger.info(f"Title: {result['title']}\nURL: {result['url']}\nSummary: {result['summary']}\n")

if __name__ == "__main__":
    asyncio.run(main())