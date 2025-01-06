import logging
import requests
from bs4 import BeautifulSoup
import asyncio
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SCRAPED_URLS = set()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def filter_new_articles(articles: List[Dict]) -> List[Dict]:
    return [a for a in articles if a["url"] not in SCRAPED_URLS and not SCRAPED_URLS.add(a["url"])]

async def scrape_axios() -> List[Dict]:
    try:
        response = requests.get("https://www.axios.com/technology/automation-and-ai", headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = []
        
        for article in soup.select('article')[:5]:
            try:
                title = article.select_one('h2').text.strip()
                url = article.select_one('a')['href']
                preview = article.select_one('.description, .preview').text.strip()
                
                if all([title, url, preview]):
                    articles.append({
                        "title": title,
                        "url": url,
                        "summary": preview[:200] + "..." if len(preview) > 200 else preview,
                        "source": "Axios"
                    })
            except Exception as e:
                logger.error(f"Error parsing Axios article: {e}")
                
        return articles
    except Exception as e:
        logger.error(f"Error scraping Axios: {e}")
        return []

async def scrape_arxiv() -> List[Dict]:
    try:
        response = requests.get("https://arxiv.org/list/cs.AI/recent", headers=HEADERS)
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = []
        
        for article in soup.select('.meta')[:5]:
            try:
                title = article.select_one('.title').text.replace("Title:", "").strip()
                url = article.select_one('.list-identifier a')['href']
                abstract = article.select_one('.abstract').text.strip()
                
                if all([title, url, abstract]):
                    articles.append({
                        "title": title,
                        "url": url,
                        "summary": abstract[:200] + "..." if len(abstract) > 200 else abstract,
                        "source": "arXiv"
                    })
            except Exception as e:
                logger.error(f"Error parsing arXiv article: {e}")
                
        return articles
    except Exception as e:
        logger.error(f"Error scraping arXiv: {e}")
        return []

async def scrape_all_sites() -> List[Dict]:
    scrapers = [scrape_axios, scrape_arxiv]
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