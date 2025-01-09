"""
GPT Trainer API client module that handles all communication with the AI service.
"""

from typing import Optional, Dict, Any, AsyncGenerator
import aiohttp
import asyncio
import logging
import json
from config import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GPTTrainerAPIError(Exception):
    """Base exception for API errors."""
    pass

class ServerError(GPTTrainerAPIError):
    """Server returned a 5xx error."""
    pass

class APIResponseError(GPTTrainerAPIError):
    """API returned an unexpected response."""
    pass

class GPTTrainerAPI:
    """
    Asynchronous client for the GPT Trainer API service.
    Implements connection pooling and rate limiting for optimal performance.
    """
    
    def __init__(self):
        """Initialize the API client."""
        self.base_url = "https://app.gpt-trainer.com/api/v1"
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {config.GPT_TRAINER_TOKEN}'
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10)

    async def __aenter__(self):
        """Create session if needed."""
        if not self._session:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup session."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _make_request(self, method: str, endpoint: str, retries: int = 3, **kwargs) -> Dict[str, Any]:
        """Make an API request with retry logic."""
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
                            return {
                                'success': True,
                                'message': 'Resource already exists',
                                'status': 'existing'
                            }
                        
                        if response.status >= 500:
                            last_error = ServerError(f"Server error: {response.status}")
                            if attempt < retries - 1:
                                wait_time = (attempt + 1) * 2
                                logger.warning(f"Server error. Retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                continue
                            raise last_error
                        
                        response.raise_for_status()
                        return await response.json()

            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Request failed. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                raise APIResponseError(f"Request failed: {str(e)}")

        raise last_error or APIResponseError("Maximum retries exceeded")

    async def _stream_response(self, endpoint: str, data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Stream response from API."""
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
                                decoded = decoded[6:]
                            if decoded.strip():
                                yield decoded
                        except Exception as e:
                            logger.error(f"Stream decode error: {e}")

    async def create_chat_session(self) -> str:
        """Create a new chat session and return session UUID."""
        try:
            endpoint = f'chatbot/{config.CHATBOT_UUID}/session/create'
            response = await self._make_request('POST', endpoint)
            return response['uuid']
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            raise

    async def get_response(self, session_uuid: str, message: str, context: str = "") -> str:
        """Get AI response using streaming endpoint."""
        try:
            endpoint = f'session/{session_uuid}/message/stream'
            query = f"{context}\n\nUser: {message}" if context else f"User: {message}"
            
            response_chunks = []
            
            async for chunk in self._stream_response(endpoint, {'query': query}):
                try:
                    data = json.loads(chunk)
                    if isinstance(data, dict) and 'text' in data:
                        response_chunks.append(data['text'])
                except json.JSONDecodeError:
                    response_chunks.append(chunk)
                    
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
                return "I'm having trouble processing your request."

    async def upload_data_source(self, url: str) -> Dict[str, Any]:
        """Upload a URL to the knowledge base."""
        try:
            endpoint = f'chatbot/{config.CHATBOT_UUID}/data-source/url'
            return await self._make_request('POST', endpoint, json={'url': url})
        except Exception as e:
            logger.error(f"Failed to upload URL: {e}")
            return {'success': False, 'error': str(e)}

    async def summarize_content(self, url: str, content: str) -> Dict[str, Any]:
        """Get a structured summary of the content."""
        try:
            # Try direct summary endpoint
            endpoint = f'chatbot/{config.CHATBOT_UUID}/session/summary'
            prompt = """Provide a structured summary with:
                       - Key Points
                       - Main Takeaway"""
            
            try:
                response = await self._make_request('POST', endpoint, json={
                    'url': url,
                    'content': content,
                    'prompt': prompt
                })
                if 'summary' in response:
                    return {'success': True, 'summary': response['summary']}
            except ServerError:
                pass  # Fall through to fallback

            # Fallback: Use chat session
            session_uuid = await self.create_chat_session()
            summary = await self.get_response(
                session_uuid,
                f"Please summarize this content:\n\n{content[:4000]}"
            )
            return {
                'success': True,
                'summary': summary,
                'fallback': True
            }

        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return {'success': False, 'error': str(e)}

# Create singleton instance
api_client = GPTTrainerAPI()