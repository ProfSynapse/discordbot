import asyncio
from playwright.async_api import async_playwright
import logging
from config import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

SCRAPED_URLS = set()

def filter_new_articles(articles):
    # Only return articles not seen before.
    new_articles = []
    for a in articles:
        if a["url"] not in SCRAPED_URLS:
            SCRAPED_URLS.add(a["url"])
            new_articles.append(a)
    return new_articles

async def scrape_axios(page):
    await page.goto("https://www.axios.com/technology/automation-and-ai")
    articles = await page.query_selector_all("article")
    results = []
    for article in articles[:5]:  # Limit to 5 most recent articles
        try:
            title = await article.query_selector_eval("h2", "el => el.innerText")
            url = await article.query_selector_eval("a", "el => el.href")
            # Just get the preview text/description
            preview = await article.query_selector_eval(".description, .preview", "el => el.innerText")
            if all([title, url, preview]):
                results.append({
                    "title": title.strip(),
                    "url": url,
                    "summary": preview[:200] + "..." if len(preview) > 200 else preview
                })
        except Exception as e:
            logging.error(f"Error scraping Axios article: {e}")
    return results

async def scrape_arxiv(page):
    await page.goto("https://arxiv.org/list/cs.AI/recent")
    articles = await page.query_selector_all(".meta")
    results = []
    for article in articles[:5]:
        try:
            title = await article.query_selector_eval(".title", "el => el.innerText")
            url = await article.query_selector_eval(".list-identifier a", "el => el.href")
            abstract = await article.query_selector_eval(".abstract", "el => el.innerText")
            if all([title, url, abstract]):
                results.append({
                    "title": title.replace("Title:", "").strip(),
                    "url": url,
                    "summary": abstract[:200] + "..." if len(abstract) > 200 else abstract
                })
        except Exception as e:
            logging.error(f"Error scraping arXiv article: {e}")
    return results

async def scrape_all_sites():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        results = []
        
        # Dictionary of scraping functions
        scrapers = {
            'Axios': scrape_axios,
            'arXiv': scrape_arxiv,
            # Add other scrapers here
        }
        
        for source, scraper in scrapers.items():
            try:
                articles = await scraper(page)
                for article in articles:
                    article['source'] = source  # Add source to each article
                results.extend(articles)
            except Exception as e:
                logging.error(f"Error scraping {source}: {e}")
        
        await browser.close()
        return filter_new_articles(results)

async def main():
    results = await scrape_all_sites()
    for result in results:
        logging.info(f"Title: {result['title']}\nURL: {result['url']}\nSummary: {result['summary']}\n")

if __name__ == "__main__":
    asyncio.run(main())