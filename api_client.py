"""
GPT Trainer API client module that handles all communication with the AI service.
Provides an async context manager interface for efficient connection management
and implements rate limiting and error handling.
"""

from typing import Optional, Dict, Any
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
        """Get an AI response with improved error handling."""
        try:
            endpoint = f'session/{session_uuid}/message'
            data = await self._make_request(
                'POST', 
                endpoint,
                retries=3,
                json={'query': f"{context}\nUser: {message}"}
            )
            return data.get('response', "I apologize, but I couldn't generate a response at this time.")
        except ServerError as e:
            logging.error(f"Server error in get_response: {e}")
            return "I'm experiencing technical difficulties with my server. Please try again in a few minutes."
        except APIResponseError as e:
            logging.error(f"API error in get_response: {e}")
            try:
                new_session_uuid = await self.create_chat_session()
                data = await self._make_request(
                    'POST',
                    f'session/{new_session_uuid}/message',
                    retries=2,
                    json={'query': f"{context}\nUser: {message}"}
                )
                return data.get('response', "I apologize, but I couldn't generate a response at this time.")
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
