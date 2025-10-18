#!/usr/bin/env python3
"""
Test script for Discord Bot with Google Imagen integration.
Validates configuration and tests core functionality.
"""

import os
import sys
import asyncio
from typing import Dict, List, Tuple

# ANSI color codes for pretty output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(60)}{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")

def print_success(text: str):
    """Print success message."""
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text: str):
    """Print error message."""
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text: str):
    """Print warning message."""
    print(f"{YELLOW}⚠ {text}{RESET}")

def print_info(text: str):
    """Print info message."""
    print(f"{BLUE}ℹ {text}{RESET}")


class BotTester:
    """Test suite for Discord bot configuration and functionality."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.results: List[Tuple[str, bool, str]] = []
    
    def test_env_file(self) -> bool:
        """Test if .env file exists."""
        print_info("Checking for .env file...")
        if os.path.exists('.env'):
            print_success(".env file found")
            return True
        else:
            print_error(".env file not found")
            print_info("Copy .env.example to .env and fill in your values")
            return False
    
    def test_required_env_vars(self) -> Dict[str, bool]:
        """Test required environment variables."""
        print_info("Checking required environment variables...")
        
        required_vars = {
            'DISCORD_TOKEN': 'Discord bot token',
            'GPT_TRAINER_TOKEN': 'GPT Trainer API token',
            'CHATBOT_UUID': 'GPT Trainer chatbot UUID',
            'GOOGLE_API_KEY': 'Google API key for Imagen',
        }
        
        results = {}
        for var, description in required_vars.items():
            value = os.getenv(var)
            if value and value != f"your_{var.lower()}":
                print_success(f"{var}: {description}")
                results[var] = True
            else:
                print_error(f"{var}: Missing or not configured")
                results[var] = False
        
        return results
    
    def test_optional_env_vars(self):
        """Test optional environment variables."""
        print_info("Checking optional environment variables...")
        
        optional_vars = {
            'CONTENT_CHANNEL_ID': 'Discord channel for automated content',
            'YOUTUBE_API_KEY': 'YouTube API key',
        }
        
        for var, description in optional_vars.items():
            value = os.getenv(var)
            if value and value != f"your_{var.lower()}":
                print_success(f"{var}: {description} (configured)")
            else:
                print_warning(f"{var}: {description} (not configured - content scheduling disabled)")
                self.warnings += 1
    
    def test_imports(self) -> bool:
        """Test if all required packages are installed."""
        print_info("Checking Python package imports...")
        
        packages = {
            'discord': 'discord.py',
            'aiohttp': 'aiohttp',
            'google.genai': 'google-genai',
            'feedparser': 'feedparser',
            'googleapiclient': 'google-api-python-client',
            'bs4': 'beautifulsoup4',
        }
        
        all_good = True
        for module, package in packages.items():
            try:
                __import__(module.split('.')[0])
                print_success(f"{package}")
            except ImportError:
                print_error(f"{package} - Run: pip install {package}")
                all_good = False
        
        return all_good
    
    async def test_google_api(self) -> bool:
        """Test Google API connection."""
        print_info("Testing Google API connection...")
        
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key or api_key.startswith('your_'):
            print_error("Google API key not configured")
            return False
        
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            print_success("Google API client initialized successfully")
            print_info("Note: Full API test requires actual generation (skipped)")
            return True
        except Exception as e:
            print_error(f"Google API test failed: {e}")
            return False
    
    async def test_gpt_trainer_api(self) -> bool:
        """Test GPT Trainer API connection."""
        print_info("Testing GPT Trainer API connection...")
        
        token = os.getenv('GPT_TRAINER_TOKEN')
        uuid = os.getenv('CHATBOT_UUID')
        
        if not token or token.startswith('your_'):
            print_error("GPT Trainer token not configured")
            return False
        
        if not uuid or uuid.startswith('your_'):
            print_error("Chatbot UUID not configured")
            return False
        
        try:
            import aiohttp
            
            url = f"https://app.gpt-trainer.com/api/v1/chatbot/{uuid}/session/create"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        print_success(f"GPT Trainer API connected - Session: {data.get('uuid', 'N/A')[:8]}...")
                        return True
                    else:
                        print_error(f"GPT Trainer API returned status {response.status}")
                        return False
        except Exception as e:
            print_error(f"GPT Trainer API test failed: {e}")
            return False
    
    def test_config_file(self) -> bool:
        """Test if config.py loads successfully."""
        print_info("Testing config.py...")
        
        try:
            from config import config
            print_success("config.py loaded successfully")
            return True
        except Exception as e:
            print_error(f"config.py failed to load: {e}")
            return False
    
    def test_image_generator(self) -> bool:
        """Test if image generator module loads."""
        print_info("Testing image_generator.py...")
        
        try:
            from image_generator import ImageGenerator, ImageModel, ImageSize
            print_success("ImageGenerator module loaded")
            print_info(f"Available models: {', '.join([m.name for m in ImageModel])}")
            return True
        except Exception as e:
            print_error(f"ImageGenerator failed to load: {e}")
            return False
    
    def test_api_client(self) -> bool:
        """Test if API client loads."""
        print_info("Testing api_client.py...")
        
        try:
            from api_client import api_client
            print_success("API client loaded successfully")
            return True
        except Exception as e:
            print_error(f"API client failed to load: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests and display results."""
        print_header("Discord Bot Configuration Tests")
        
        # Test 1: .env file
        print_header("1. Environment File")
        if not self.test_env_file():
            print_error("\nCannot continue without .env file")
            return False
        
        # Test 2: Required environment variables
        print_header("2. Required Configuration")
        env_results = self.test_required_env_vars()
        if not all(env_results.values()):
            print_error("\nSome required variables are missing")
            self.failed += sum(1 for v in env_results.values() if not v)
        else:
            self.passed += len(env_results)
        
        # Test 3: Optional environment variables
        print_header("3. Optional Configuration")
        self.test_optional_env_vars()
        
        # Test 4: Python packages
        print_header("4. Python Packages")
        if self.test_imports():
            print_success("All required packages installed")
            self.passed += 1
        else:
            print_error("Some packages are missing - run: pip install -r requirements.txt")
            self.failed += 1
        
        # Test 5: Config module
        print_header("5. Configuration Module")
        if self.test_config_file():
            self.passed += 1
        else:
            self.failed += 1
        
        # Test 6: Core modules
        print_header("6. Core Modules")
        modules_ok = True
        
        if self.test_image_generator():
            self.passed += 1
        else:
            self.failed += 1
            modules_ok = False
        
        if self.test_api_client():
            self.passed += 1
        else:
            self.failed += 1
            modules_ok = False
        
        # Test 7: API connections (only if config is good)
        if all(env_results.values()) and modules_ok:
            print_header("7. API Connectivity")
            
            if await self.test_google_api():
                self.passed += 1
            else:
                self.failed += 1
            
            if await self.test_gpt_trainer_api():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_header("7. API Connectivity")
            print_warning("Skipping API tests due to configuration errors")
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        print_header("Test Summary")
        
        total = self.passed + self.failed
        
        if self.failed == 0:
            print_success(f"\n🎉 All tests passed! ({self.passed}/{total})")
            if self.warnings > 0:
                print_warning(f"   {self.warnings} optional feature(s) not configured")
            print_success("\n✓ Your bot is ready to run!")
            print_info("\nStart your bot with: python main.py")
        else:
            print_error(f"\n❌ {self.failed}/{total} tests failed")
            print_success(f"✓ {self.passed}/{total} tests passed")
            if self.warnings > 0:
                print_warning(f"⚠ {self.warnings} warning(s)")
            print_error("\n✗ Please fix the errors above before running the bot")
        
        print()


async def main():
    """Main test runner."""
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print_info("Loaded environment variables from .env")
    except ImportError:
        print_warning("python-dotenv not installed - reading from system environment")
        print_info("Install with: pip install python-dotenv")
    
    # Run tests
    tester = BotTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\n\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n\nFatal error: {e}")
        sys.exit(1)
