#!/usr/bin/env python3
"""
Integration tests for Discord Bot APIs.
Tests actual API calls to Google Imagen and GPT Trainer.

WARNING: These tests make real API calls and may incur costs.
"""

import os
import sys
import asyncio
from typing import Optional

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'

def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(70)}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")

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

def confirm_test(test_name: str, cost_warning: str = "") -> bool:
    """Ask user to confirm running a test."""
    print(f"\n{BOLD}Test: {test_name}{RESET}")
    if cost_warning:
        print_warning(cost_warning)
    
    response = input(f"{YELLOW}Run this test? (y/n): {RESET}").strip().lower()
    return response in ['y', 'yes']


class APITester:
    """Integration test suite for bot APIs."""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
    
    async def test_gpt_trainer_chat(self) -> bool:
        """Test GPT Trainer chat API with actual message."""
        print_info("Testing GPT Trainer chat API...")
        
        try:
            from api_client import api_client
            
            # Create a chat session
            print_info("Creating chat session...")
            session_uuid = await api_client.create_chat_session()
            print_info(f"Session created: {session_uuid[:8]}...")
            
            # Send a test message
            test_prompt = "Hello! This is a test message. Please respond briefly."
            print_info(f"Sending test prompt: '{test_prompt}'")
            
            response = await api_client.get_response(session_uuid, test_prompt)
            
            if response:
                print_success(f"Received response ({len(response)} characters)")
                print_info(f"Response preview: {response[:100]}...")
                return True
            else:
                print_error("Received empty response")
                return False
                
        except Exception as e:
            print_error(f"Chat API test failed: {e}")
            return False
    
    async def test_gpt_trainer_upload(self) -> bool:
        """Test GPT Trainer knowledge base upload."""
        print_info("Testing GPT Trainer data source upload API...")
        
        try:
            from api_client import api_client
            
            # Use a real, accessible URL for testing
            test_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
            print_info(f"Uploading test URL: {test_url}")
            
            success = await api_client.upload_data_source(test_url)
            
            if success:
                print_success("Data source uploaded successfully")
                print_warning("Note: It may take a few minutes for GPT Trainer to process this")
                return True
            else:
                print_error("Upload failed")
                return False
                
        except Exception as e:
            print_error(f"Upload API test failed: {e}")
            return False
    
    async def test_google_imagen_fast(self) -> bool:
        """Test Google Imagen API with fast model."""
        print_info("Testing Google Imagen API (fast model)...")
        
        try:
            from image_generator import ImageGenerator
            from config import config
            
            generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
            
            test_prompt = "a simple red circle on white background"
            # Fast model doesn't support custom sizes, use default (1K)
            print_info(f"Generating test image: '{test_prompt} --fast'")
            print_info("Using default size (1K) - fast model doesn't support size customization")
            
            # Parse flags to get config
            clean_prompt, img_config = generator.parse_flags(f"{test_prompt} --fast")
            
            # Generate image
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if image_data and len(image_data) > 0:
                print_success("Image generated successfully!")
                print_info(f"Image type: {content_type}")
                print_info(f"Image size: {len(image_data)} bytes")
                print_info(f"Model: {img_config.model.value}")
                return True
            else:
                print_error("Image generation failed - no data returned")
                return False
                
        except Exception as e:
            print_error(f"Imagen API test failed: {e}")
            import traceback
            print_error(traceback.format_exc())
            return False
    
    async def test_google_imagen_standard(self) -> bool:
        """Test Google Imagen API with standard model."""
        print_info("Testing Google Imagen API (standard model)...")
        
        try:
            from image_generator import ImageGenerator
            from config import config
            
            generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
            
            test_prompt = "a blue square"
            # Standard model supports 1K or 2K
            print_info(f"Generating test image: '{test_prompt} --standard --square'")
            print_info("Using 1K size (standard model supports 1K or 2K)")
            
            clean_prompt, img_config = generator.parse_flags(f"{test_prompt} --standard --square")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if image_data and len(image_data) > 0:
                print_success("Image generated successfully with standard model!")
                print_info(f"Model: {img_config.model.value}")
                print_info(f"Size: {len(image_data)} bytes")
                return True
            else:
                print_error("Image generation failed")
                return False
                
        except Exception as e:
            print_error(f"Imagen standard API test failed: {e}")
            return False
    
    async def test_google_imagen_ultra(self) -> bool:
        """Test Google Imagen API with ultra model."""
        print_info("Testing Google Imagen API (ultra model)...")
        
        try:
            from image_generator import ImageGenerator
            from config import config
            
            generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
            
            test_prompt = "a green triangle"
            # Ultra model supports 1K or 2K
            print_info(f"Generating test image: '{test_prompt} --ultra --square'")
            print_warning("Ultra model is slower and may cost more")
            
            clean_prompt, img_config = generator.parse_flags(f"{test_prompt} --ultra --square")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if image_data and len(image_data) > 0:
                print_success("Image generated successfully with ultra model!")
                print_info(f"Model: {img_config.model.value}")
                return True
            else:
                print_error("Image generation failed")
                return False
                
        except Exception as e:
            print_error(f"Imagen ultra API test failed: {e}")
            return False
    
    async def test_image_sizes(self) -> bool:
        """Test different image sizes."""
        print_info("Testing different image sizes...")
        print_warning("Note: Fast model doesn't support custom sizes")
        print_info("Testing with standard model (supports 1K and 2K)")
        
        try:
            from image_generator import ImageGenerator
            from config import config
            
            generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
            
            # Test 1K
            print_info("Testing 1K size...")
            clean_prompt, img_config = generator.parse_flags("test size 1K --standard --square")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if not image_data or len(image_data) == 0:
                print_error("1K size test failed")
                return False
            
            print_success(f"1K size works ({len(image_data)} bytes)")
            
            # Test 2K
            print_info("Testing 2K size...")
            clean_prompt, img_config = generator.parse_flags("test size 2K --standard --2k")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if not image_data or len(image_data) == 0:
                print_error("2K size test failed")
                return False
            
            print_success(f"2K size works ({len(image_data)} bytes)")
            return True
            
        except Exception as e:
            print_error(f"Size test failed: {e}")
            return False
    
    async def test_image_formats(self) -> bool:
        """Test different image formats."""
        print_info("Testing different image formats...")
        
        try:
            from image_generator import ImageGenerator
            from config import config
            
            generator = ImageGenerator(api_key=config.GOOGLE_API_KEY)
            
            # Test PNG with fast model
            print_info("Testing PNG format (fast model)...")
            clean_prompt, img_config = generator.parse_flags("test png --fast --png")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if not image_data or len(image_data) == 0:
                print_error("PNG format test failed")
                return False
            
            print_success(f"PNG format works ({content_type}, {len(image_data)} bytes)")
            
            # Test JPEG with fast model
            print_info("Testing JPEG format (fast model)...")
            clean_prompt, img_config = generator.parse_flags("test jpeg --fast --jpeg")
            content_type, image_data = await generator.generate_image(clean_prompt, img_config)
            
            if not image_data or len(image_data) == 0:
                print_error("JPEG format test failed")
                return False
            
            print_success(f"JPEG format works ({content_type}, {len(image_data)} bytes)")
            return True
            
        except Exception as e:
            print_error(f"Format test failed: {e}")
            return False
    
    async def test_content_scraper(self) -> bool:
        """Test content scraper functionality."""
        print_info("Testing content scraper...")
        
        try:
            from scraper.content_scraper import scrape_article_content
            
            # Test with a simple, accessible URL
            test_url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
            print_info(f"Scraping test URL: {test_url}")
            
            content = await scrape_article_content(test_url)
            
            if content and len(content) > 100:
                print_success(f"Successfully scraped content ({len(content)} characters)")
                print_info(f"Content preview: {content[:100]}...")
                return True
            else:
                print_error("No content scraped or content too short")
                return False
                
        except Exception as e:
            print_error(f"Content scraper test failed: {e}")
            return False
    
    async def run_all_tests(self, skip_confirmations: bool = False):
        """Run all API integration tests."""
        
        print_header("Discord Bot API Integration Tests")
        
        print_warning("⚠️  WARNING: These tests make real API calls!")
        print_warning("   - Google Imagen: May incur charges (using smallest sizes)")
        print_warning("   - GPT Trainer: Uses your API quota")
        print_warning("   - Content Scraper: Free, no API costs")
        
        if not skip_confirmations:
            print()
            response = input(f"{BOLD}Continue with API tests? (y/n): {RESET}").strip().lower()
            if response not in ['y', 'yes']:
                print_warning("Tests cancelled by user")
                return
        
        print()
        
        # Test 1: GPT Trainer Chat
        print_header("1. GPT Trainer Chat API")
        if skip_confirmations or confirm_test(
            "GPT Trainer Chat", 
            "Sends one test message to your chatbot"
        ):
            if await self.test_gpt_trainer_chat():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 2: GPT Trainer Upload
        print_header("2. GPT Trainer Knowledge Base Upload")
        if skip_confirmations or confirm_test(
            "GPT Trainer Upload",
            "Uploads a Wikipedia article to your knowledge base"
        ):
            if await self.test_gpt_trainer_upload():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 3: Google Imagen Fast
        print_header("3. Google Imagen (Fast Model)")
        if skip_confirmations or confirm_test(
            "Google Imagen Fast Model",
            "Generates one 256x256 image (minimal cost)"
        ):
            if await self.test_google_imagen_fast():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 4: Google Imagen Standard
        print_header("4. Google Imagen (Standard Model)")
        if skip_confirmations or confirm_test(
            "Google Imagen Standard Model",
            "Generates one 256x256 image (low cost)"
        ):
            if await self.test_google_imagen_standard():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 5: Google Imagen Ultra
        print_header("5. Google Imagen (Ultra Model)")
        if skip_confirmations or confirm_test(
            "Google Imagen Ultra Model",
            "Generates one 256x256 image (higher cost, slower)"
        ):
            if await self.test_google_imagen_ultra():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 6: Image Sizes
        print_header("6. Image Size Options")
        if skip_confirmations or confirm_test(
            "Image Size Options",
            "Tests portrait and landscape sizes (2 small images)"
        ):
            if await self.test_image_sizes():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 7: Image Formats
        print_header("7. Image Format Options")
        if skip_confirmations or confirm_test(
            "Image Format Options",
            "Tests PNG and JPEG formats (2 small images)"
        ):
            if await self.test_image_formats():
                self.passed += 1
            else:
                self.failed += 1
        else:
            print_warning("Skipped")
            self.skipped += 1
        
        # Test 8: Content Scraper (Free)
        print_header("8. Content Scraper")
        print_info("This test is free (no API costs)")
        if await self.test_content_scraper():
            self.passed += 1
        else:
            self.failed += 1
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        print_header("Test Summary")
        
        total = self.passed + self.failed + self.skipped
        
        print_success(f"✓ Passed: {self.passed}/{total}")
        if self.failed > 0:
            print_error(f"✗ Failed: {self.failed}/{total}")
        if self.skipped > 0:
            print_warning(f"⊘ Skipped: {self.skipped}/{total}")
        
        print()
        
        if self.failed == 0 and self.passed > 0:
            print_success("🎉 All executed tests passed!")
            print_info("\n✓ Your APIs are working correctly!")
            print_info("✓ Ready to deploy your bot!")
        elif self.failed > 0:
            print_error("\n❌ Some tests failed")
            print_info("Please check the errors above and verify your API keys")
        else:
            print_warning("\n⊘ No tests were run")
        
        print()


async def main():
    """Main test runner."""
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print_info("Loaded environment variables from .env")
    except ImportError:
        print_warning("python-dotenv not installed - using system environment")
    
    # Check if we should skip confirmations (for CI/automated testing)
    skip_confirmations = '--yes' in sys.argv or '-y' in sys.argv
    
    # Run tests
    tester = APITester()
    await tester.run_all_tests(skip_confirmations=skip_confirmations)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\n\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n\nFatal error: {e}")
        import traceback
        print_error(traceback.format_exc())
        sys.exit(1)
