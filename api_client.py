"""
GPT Trainer API client module that handles all communication with the AI service.
Provides an async context manager interface for efficient connection management
and implements rate limiting and error handling.
"""

from typing import Optional, Dict, Any, AsyncGenerator
import aiohttp
import asyncio
import logging
import json
from config import config
from aiohttp import ClientError

class GPTTrainerAPIError(Exception):
    """Base exception for API errors."""
    pass

class ServerError(GPTTrainerAPIError):
    """Raised when the server returns a 5xx error."""
    pass

class APIResponseError(GPTTrainerAPIError):
    """Raised when the API returns an unexpected response."""
    pass

class GPTTrainerAPI:
    """
    Asynchronous client for the GPT Trainer API service.
    Implements connection pooling and rate limiting for optimal performance.
    
    Usage:
        async with api_client as client:
            session_uuid = await client.create_chat_session()
            response = await client.get_response(session_uuid, "Hello!")
    """
    
    def __init__(self):
        """Initialize the API client with configuration and session management."""
        self.base_url = "https://app.gpt-trainer.com/api/v1"
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.GPT_TRAINER_TOKEN}'
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10)  # Increased timeouts

    async def __aenter__(self):
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
            self._session = None

    async def _make_request(self, method: str, endpoint: str, retries: int = 3, **kwargs) -> Dict[Any, Any]:
        """Make an API request with retry logic and detailed error handling."""
        if not self._session:
            self._session = aiohttp.ClientSession()

        url = f'{self.base_url}/{endpoint}'
        kwargs['headers'] = self.headers
        last_error = None

        for attempt in range(retries):
            try:
                async with self._lock:
                    async with self._session.request(method, url, **kwargs) as response:
                        if response.status >= 500:
                            last_error = ServerError(f"Server error: {response.status} - Attempt {attempt + 1}/{retries}")
                            if attempt < retries - 1:
                                wait_time = (attempt + 1) * 2  # Exponential backoff
                                logging.warning(f"{last_error}. Retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                continue
                            raise last_error
                        
                        response.raise_for_status()
                        return await response.json()
                        
            except ServerError as e:
                last_error = e
                if attempt == retries - 1:
                    raise
            except ClientError as e:
                last_error = APIResponseError(f"API request failed: {str(e)}")
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 2
                    logging.warning(f"Request failed. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                raise last_error

        raise last_error or APIResponseError("Maximum retries exceeded")

    async def _make_streaming_request(self, endpoint: str, data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Make a streaming API request."""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)

        url = f'{self.base_url}/{endpoint}'
        try:
            async with self._lock:
                async with self._session.post(url, headers=self.headers, json=data) as response:
                    if response.status >= 500:
                        raise ServerError(f"Server error: {response.status}")
                    
                    response.raise_for_status()
                    async for line in response.content.iter_any():
                        if line:
                            try:
                                decoded = line.decode('utf-8').strip()
                                if decoded.startswith('data: '):
                                    decoded = decoded[6:]  # Remove 'data: ' prefix
                                if decoded:
                                    yield decoded
                            except Exception as e:
                                logging.error(f"Error decoding stream: {e}")
                                continue
        except Exception as e:
            logging.error(f"Streaming request failed: {e}")
            raise

    async def create_chat_session(self) -> str:
        """
        Create a new chat session with the GPT Trainer service.

        Returns:
            str: UUID of the created session

        Raises:
            aiohttp.ClientError: If the API request fails
        """
        endpoint = f'chatbot/{config.CHATBOT_UUID}/session/create'
        data = await self._make_request('POST', endpoint)
        return data['uuid']

    async def get_response(self, session_uuid: str, message: str, context: str = "") -> str:
        """Get an AI response using streaming endpoint."""
        try:
            endpoint = f'session/{session_uuid}/message/stream'
            full_response = []
            last_chunk_ended_with_space = False
            
            async for chunk in self._make_streaming_request(
                endpoint,
                {'query': f"{context}\nUser: {message}"}
            ):
                try:
                    # Try to parse JSON response
                    data = json.loads(chunk)
                    if isinstance(data, dict) and 'text' in data:
                        text = data['text']
                        
                        # Debug logging
                        logging.debug(f"Received chunk: '{text}' (len={len(text)})")
                        
                        # Add space between chunks if needed
                        if full_response and not last_chunk_ended_with_space and not text.startswith(' '):
                            full_response.append(' ')
                        
                        full_response.append(text)
                        last_chunk_ended_with_space = text.endswith(' ')
                except json.JSONDecodeError:
                    # If not JSON, clean and append raw chunk
                    text = chunk.strip()
                    if text:
                        if full_response and not last_chunk_ended_with_space and not text.startswith(' '):
                            full_response.append(' ')
                        full_response.append(text)
                        last_chunk_ended_with_space = text.endswith(' ')
            
            # Join and clean up the final response
            final_response = ''.join(full_response).strip()
            # Normalize multiple spaces
            final_response = ' '.join(final_response.split())
            
            return final_response if final_response else "I apologize, but I couldn't generate a response."
                    
        except ServerError as e:
            logging.error(f"Server error in get_response: {e}")
            return "I'm experiencing technical difficulties with my server. Please try again in a few minutes."
        except Exception as e:
            logging.error(f"Error in get_response: {e}")
            try:
                # Fallback to creating new session
                new_session_uuid = await self.create_chat_session()
                return await self.get_response(new_session_uuid, message, context)
            except Exception as retry_error:
                logging.error(f"Retry failed: {retry_error}")
                return "I'm having trouble processing your request. Please try again in a moment."

    async def upload_data_source(self, url: str) -> bool:
        """Upload a new data source URL to the chatbot."""
        endpoint = f'chatbot/{config.CHATBOT_UUID}/data-source/url'
        try:
            await self._make_request('POST', endpoint, json={'url': url})
            return True
        except Exception as e:
            logging.error(f"Failed to upload data source: {e}")
            return False

# Create a singleton instance
api_client = GPTTrainerAPI()
