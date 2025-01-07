import logging
from typing import Optional
import re
from pyppeteer import launch
import os
import asyncio

logger = logging.getLogger(__name__)

async def scrape_article_content(url: str, max_retries: int = 3) -> Optional[str]:
    """
    Scrapes article content using Pyppeteer with retries.
    Returns the main article text content.
    """
    for attempt in range(max_retries):
        browser = None
        try:
            chrome_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--disable-extensions',
                '--single-process',
                '--no-zygote',
                '--no-first-run',
                '--disable-notifications',
                '--disable-background-networking',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--metrics-recording-only',
                '--mute-audio',
                '--disable-features=site-per-process',
                '--disable-features=TranslateUI',
                '--disable-breakpad',
                '--disable-backing-store-limit',
                '--disable-component-extensions-with-background-pages',
                '--disable-ipc-flooding-protection',
                '--enable-features=NetworkService,NetworkServiceInProcess',
                '--window-size=1920x1080',
                '--disable-gpu-sandbox',
                '--disable-dev-profile'
            ]

            browser = await launch(
                headless=True,
                args=chrome_args,
                handleSIGINT=False,
                handleSIGTERM=False,
                handleSIGHUP=False,
                ignoreHTTPSErrors=True,
                dumpio=True,
                timeout=120000,  # 120 second timeout
                env={
                    'DISPLAY': ':99',
                    'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/var/run/dbus/system_bus_socket',
                    'NO_SANDBOX': '1'
                }
            )

            # After browser launch, add a small delay
            await asyncio.sleep(2)

            # Set up a new page with longer timeout
            page = await browser.newPage()
            await page.setDefaultNavigationTimeout(60000)  # 60 second timeout
            
            # Additional error handlers
            page.on('error', lambda err: logger.error(f'Page error: {err}'))
            page.on('pageerror', lambda err: logger.error(f'Page error: {err}'))

            # Set user agent to avoid detection
            await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36')

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
            
            if content:
                # Clean up the content
                content = re.sub(r'\s+', ' ', content).strip()  # Remove extra whitespace
                content = re.sub(r'Share\s*this[\s\S]*$', '', content)  # Remove sharing section
                return content
                
            return None
            
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")
            if browser:
                try:
                    await browser.close()
                except:
                    pass
            if attempt == max_retries - 1:
                logger.error("All retry attempts failed")
                return None
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
            continue

        finally:
            if browser:
                try:
                    await browser.close()
                except Exception as e:
                    logger.error(f"Error closing browser: {str(e)}")
