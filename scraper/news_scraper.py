import logging
import requests
from bs4 import BeautifulSoup
import asyncio
from typing import List, Dict
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SCRAPED_URLS = set()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def filter_new_articles(articles: List[Dict]) -> List[Dict]:
    return [a for a in articles if a["url"] not in SCRAPED_URLS and not SCRAPED_URLS.add(a["url"])]

async def scrape_axios() -> List[Dict]:
    """Switch to Axios RSS feed instead of web scraping"""
    try:
        logger.info("Starting Axios scrape")
        response = requests.get("https://www.axios.com/feed/", headers=HEADERS)
        response.raise_for_status()
        
        rss = ET.fromstring(response.content)
        articles = []
        
        # Get items with "artificial intelligence" or "AI" in title/description
        for item in rss.findall('.//item')[:10]:
            try:
                title = item.find('title').text
                url = item.find('link').text
                description = item.find('description').text
                
                # Only include AI-related articles
                if any(term.lower() in (title + description).lower() 
                      for term in ['artificial intelligence', 'ai', 'machine learning']):
                    articles.append({
                        "title": title,
                        "url": url,
                        "summary": description[:200] + "..." if len(description) > 200 else description,
                        "source": "Axios"
                    })
            except Exception as e:
                logger.error(f"Error parsing Axios RSS item: {e}", exc_info=True)
                
        logger.info(f"Successfully scraped {len(articles)} Axios articles")
        return articles
    except Exception as e:
        logger.error(f"Error scraping Axios: {e}", exc_info=True)
        return []

async def scrape_arxiv() -> List[Dict]:
    try:
        logger.info("Starting arXiv scrape")
        
        # Get papers from last 2 days only
        days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y%m%d')
        base_url = "http://export.arxiv.org/api/query"
        query_params = {
            'search_query': 'cat:cs.AI+AND+submittedDate:[{}2359+TO+*]'.format(days_ago),
            'sortBy': 'submittedDate',
            'sortOrder': 'descending',
            'max_results': 10
        }
        
        response = requests.get(base_url, params=query_params, headers=HEADERS)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        articles = []
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        
        # Keywords to filter for more relevant papers
        relevant_keywords = [
            'large language model', 'llm', 'gpt', 'transformer',
            'deep learning', 'neural network', 'machine learning',
            'artificial intelligence', 'reinforcement learning', 'graph', 'knowledge graph', 'reasoning', 'diffusion', 'image', 'security', 'prompt engineering', 'security', 'ethics'
        ]
        
        for entry in root.findall('atom:entry', ns)[:5]:
            try:
                title = entry.find('atom:title', ns).text.strip()
                url = entry.find('atom:id', ns).text
                abstract = entry.find('atom:summary', ns).text.strip()
                
                # Check if the paper is relevant based on keywords
                content = (title + ' ' + abstract).lower()
                is_relevant = any(keyword in content for keyword in relevant_keywords)
                
                if all([title, url, abstract]) and is_relevant:
                    articles.append({
                        "title": title,
                        "url": url,
                        "summary": abstract[:200] + "..." if len(abstract) > 200 else abstract,
                        "source": "arXiv"
                    })
                    logger.info(f"Found relevant arXiv paper: {title}")
            except Exception as e:
                logger.error(f"Error parsing arXiv entry: {e}", exc_info=True)
                
        logger.info(f"Successfully scraped {len(articles)} relevant arXiv articles")
        return articles
    except Exception as e:
        logger.error(f"Error scraping arXiv: {e}", exc_info=True)
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