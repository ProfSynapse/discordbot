"""
GPT Trainer API client module with improved text handling and streaming capabilities.
"""

from typing import Optional, Dict, Any, AsyncGenerator
import aiohttp
import asyncio
import logging
import json
import re
from dataclasses import dataclass
from config import config

logger = logging.getLogger(__name__)

@dataclass
class APIResponse:
    """Structured API Response"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None

class GPTTrainerAPIError(Exception):
    """Base exception for API errors."""
    pass

class ServerError(GPTTrainerAPIError):
    """Raised when the server returns a 5xx error."""
    pass

class APIResponseError(GPTTrainerAPIError):
    """Raised when the API returns an unexpected response."""
    pass

class ResponseProcessor:
    """Handles text processing and cleaning for API responses."""
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize text while preserving formatting."""
        if not text:
            return text
            
        # Basic cleaning
        text = str(text).strip()
        
        # Fix common formatting issues
        text = re.sub(r'\s+', ' ', text)  # Normalize spaces
        text = re.sub(r'(?<=:)\s+(?=\w)|(?<=\w)\s+(?=:)', '', text)  # Fix emoji sequences
        text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)  # Remove zero-width spaces
        
        # Fix markdown formatting
        text = re.sub(r'\*\s+\*', '**', text)  # Fix bold
        text = re.sub(r'_\s+_', '__', text)  # Fix underline
        text = re.sub(r'`\s+`', '``', text)  # Fix code blocks
        
        return text

    @staticmethod
    def process_chunk(chunk: str, is_json: bool = True) -> Optional[str]:
        """Process a single chunk of streaming response."""
        if not chunk:
            return None
            
        try:
            if is_json:
                data = json.loads(chunk)
                return data.get('text', '').strip()
            return chunk.strip()
        except json.JSONDecodeError:
            return chunk.strip()
        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            return None

class GPTTrainerAPI:
    """
    Asynchronous client for the GPT Trainer API service.
    Implements improved text handling and stream processing.
    """
    
    def __init__(self):
        """Initialize the API client with improved configuration."""
        self.base_url = "https://app.gpt-trainer.com/api/v1"
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.GPT_TRAINER_TOKEN}'
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self.processor = ResponseProcessor()

    async def __aenter__(self):
        """Async context manager entry."""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with proper cleanup."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        retries: int = 3, 
        **kwargs
    ) -> APIResponse:
        """Make an API request with improved error handling."""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)

        url = f'{self.base_url}/{endpoint}'
        kwargs['headers'] = self.headers
        last_error = None

        for attempt in range(retries):
            try:
                async with self._lock:
                    async with self._session.request(method, url, **kwargs) as response:
                        if response.status == 409:
                            return APIResponse(
                                success=True,
                                message='URL already exists in database',
                                data={'status': 'existing'}
                            )
                        
                        if response.status >= 500:
                            message = f"Server error: {response.status} - Attempt {attempt + 1}/{retries}"
                            if attempt < retries - 1:
                                wait_time = (attempt + 1) * 2
                                logger.warning(f"{message}. Retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                continue
                            raise ServerError(message)
                        
                        response.raise_for_status()
                        data = await response.json()
                        return APIResponse(success=True, data=data)
                        
            except ServerError as e:
                last_error = e
            except Exception as e:
                last_error = APIResponseError(f"Request failed: {str(e)}")
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Request failed. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

        return APIResponse(success=False, error=str(last_error))

    async def _stream_response(self, endpoint: str, data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Handle streaming responses with minimal processing."""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)

        url = f'{self.base_url}/{endpoint}'
        
        async with self._lock:
            async with self._session.post(url, headers=self.headers, json=data) as response:
                response.raise_for_status()
                
                async for line in response.content.iter_any():
                    if line:
                        try:
                            decoded = line.decode('utf-8')
                            if decoded.startswith('data: '):
                                decoded = decoded[6:]  # Remove 'data: ' prefix
                            if decoded.strip():  # Only yield non-empty chunks
                                yield decoded
                        except Exception as e:
                            logger.error(f"Stream decode error: {e}")
                            continue

    async def get_response(self, session_uuid: str, message: str, context: str = "") -> str:
        """Get an AI response with minimal processing."""
        try:
            endpoint = f'session/{session_uuid}/message/stream'
            query = f"{context}\n\nUser: {message}" if context else f"User: {message}"
            
            response_chunks = []
            
            async for chunk in self._stream_response(endpoint, {'query': query}):
                try:
                    # Parse JSON only if needed
                    data = json.loads(chunk)
                    if isinstance(data, dict) and 'text' in data:
                        response_chunks.append(data['text'])
                except json.JSONDecodeError:
                    # If not JSON, append as is
                    response_chunks.append(chunk)
                    
            # Simply join the chunks
            final_response = ''.join(response_chunks)
            
            return final_response if final_response else "I apologize, but I couldn't generate a response."
                        
        except Exception as e:
            logger.error(f"Error in get_response: {e}")
            try:
                # Fallback to new session
                new_session_uuid = await self.create_chat_session()
                return await self.get_response(new_session_uuid, message, context)
            except Exception as retry_error:
                logger.error(f"Retry failed: {retry_error}")
                return "I'm having trouble processing your request. Please try again."

    async def upload_data_source(self, url: str) -> APIResponse:
        """Upload a URL to the knowledge base."""
        endpoint = f'chatbot/{config.CHATBOT_UUID}/data-source/url'
        logger.info(f"Uploading URL: {url}")
        response = await self._make_request('POST', endpoint, json={'url': url})
        logger.info(f"Upload response: {response}")
        return response

    async def summarize_content(self, url: str, content: str) -> APIResponse:
        """Get a structured content summary."""
        try:
            endpoint = f'chatbot/{config.CHATBOT_UUID}/session/summary'
            prompt = """Provide a structured summary of this article:
                       Key Points:
                       - [First key point]
                       - [Second key point]
                       - [Third key point]
                       Main Takeaway: [Brief one-sentence takeaway]"""
            
            response = await self._make_request('POST', endpoint, json={
                'url': url,
                'content': content,
                'prompt': prompt
            })
            
            if response.success and response.data and 'summary' in response.data:
                return response
                
            # Fallback to streaming approach
            session_uuid = await self.create_chat_session()
            summary = await self.get_response(
                session_uuid,
                f"Please summarize:\n\n{content[:4000]}"
            )
            
            return APIResponse(
                success=True,
                data={'summary': summary},
                message='Generated using fallback method'
            )

        except Exception as e:
            logger.error(f"Summary error: {e}")
            return APIResponse(success=False, error=str(e))

# Singleton instance
api_client = GPTTrainerAPI()