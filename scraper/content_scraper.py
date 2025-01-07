import logging
from typing import Optional
import re
from pyppeteer import launch
import os

logger = logging.getLogger(__name__)

async def scrape_article_content(url: str) -> Optional[str]:
    """
    Scrapes article content using Pyppeteer.
    Returns the main article text content.
    """
    browser = None
    try:
        # Add Chrome executable path and more launch options
        chrome_args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-gpu',
            '--window-size=1920x1080',
            '--disable-software-rasterizer',
            '--disable-extensions',
            '--single-process',  # Important for Docker
            '--no-zygote',       # Important for Docker
            '--disable-setuid-sandbox',
            '--no-first-run',
            '--disable-notifications',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--disable-translate',
            '--hide-scrollbars',
            '--metrics-recording-only',
            '--mute-audio',
            '--disable-dbus',  # Disable DBus usage
        ]

        # Launch with more specific options
        browser = await launch(
            headless=True,
            args=chrome_args,
            executablePath='/usr/bin/google-chrome',  # Specify Chrome path
            handleSIGINT=False,
            handleSIGTERM=False,
            handleSIGHUP=False,
            env={
                'DISPLAY': ':99',
                'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/var/run/dbus/system_bus_socket'
            },  # Set display for Docker
            dumpio=True,  # Log browser console output
            ignoreHTTPSErrors=True,  # Add this to ignore HTTPS errors
            timeout=60000  # Increase timeout to 60 seconds
        )

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
        logger.error(f"Error scraping article content: {str(e)}", exc_info=True)
        return None
        
    finally:
        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {str(e)}")
