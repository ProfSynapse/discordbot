"""
Location: /mnt/f/Code/discordbot/api_client.py
Summary: Asynchronous API client for the GPT Trainer service. Provides a singleton
         instance (`api_client`) used by main.py, session_manager.py, and
         content_scheduler.py. Handles connection pooling, retry logic, and
         streaming responses.

Lifecycle: The aiohttp session is created lazily on first use and persists for
           the lifetime of the process. The `async with api_client` pattern is
           supported for backward compatibility but does NOT close the session
           on exit. Call `await api_client.close()` explicitly during shutdown.
"""

from typing import Optional, Dict, Any, AsyncGenerator
import aiohttp
import asyncio
import logging
import json
from config import config

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
        # Semaphore allows up to 5 concurrent API requests instead of
        # serializing everything behind a single Lock.
        self._semaphore = asyncio.Semaphore(5)
        self.timeout = aiohttp.ClientTimeout(total=30, connect=10)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Lazily create the aiohttp session on first use. Returns the session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def __aenter__(self):
        """Ensure session exists. Does NOT take ownership — exiting the
        context manager will NOT close the session. This preserves connection
        pooling across multiple `async with api_client` blocks."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """No-op. The session is long-lived and shared across the process.
        Call `await api_client.close()` explicitly during application shutdown."""
        pass

    async def close(self):
        """Explicitly close the underlying aiohttp session.
        Call this during graceful application shutdown."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _make_request(self, method: str, endpoint: str, retries: int = 3, **kwargs) -> Dict[str, Any]:
        """Make an API request with retry logic.

        The semaphore is held only for the duration of each HTTP round-trip,
        NOT during retry backoff sleeps. This prevents a slow retry from
        blocking other unrelated requests.
        """
        session = await self._ensure_session()

        url = f'{self.base_url}/{endpoint}'
        kwargs['headers'] = self.headers
        last_error = None

        for attempt in range(retries):
            try:
                async with self._semaphore:
                    async with session.request(method, url, **kwargs) as response:
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
                                # Sleep OUTSIDE the semaphore (already released
                                # because we break out of the `async with` block).
                                break  # break inner try to sleep outside semaphore
                            raise last_error

                        response.raise_for_status()
                        return await response.json()

            except ServerError:
                # Re-raised from inside the semaphore block on final attempt.
                if attempt >= retries - 1:
                    raise
                # For non-final attempts we already set last_error and broke
                # out; fall through to the sleep below.
            except Exception as e:
                last_error = e
                if attempt >= retries - 1:
                    raise APIResponseError(f"Request failed: {str(e)}")

            # Backoff sleep happens OUTSIDE the semaphore so other requests
            # can proceed while we wait.
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 2
                if not isinstance(last_error, ServerError):
                    logger.warning(f"Request failed. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        raise last_error or APIResponseError("Maximum retries exceeded")

    async def _stream_response(self, endpoint: str, data: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Stream response from API.

        The semaphore is acquired only to initiate the HTTP request, then
        released immediately. Reading the response body (which can take
        10-30s for long streams) happens WITHOUT holding the semaphore so
        other requests are not blocked.
        """
        session = await self._ensure_session()
        url = f'{self.base_url}/{endpoint}'

        # We use the lower-level _request so we can control when the
        # response object is released. The semaphore guards only the
        # connection establishment / initial headers, not the body read.
        response = None
        try:
            async with self._semaphore:
                response = await session.post(url, headers=self.headers, json=data)
                response.raise_for_status()
            # Semaphore released here; body streaming continues below.

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
        finally:
            if response is not None:
                response.release()

    async def create_chat_session(self) -> str:
        """Create a new chat session and return session UUID."""
        try:
            endpoint = f'chatbot/{config.CHATBOT_UUID}/session/create'
            response = await self._make_request('POST', endpoint)
            return response['uuid']
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            raise

    async def get_response(
        self,
        session_uuid: str,
        message: str,
        context: str = "",
        _is_retry: bool = False,
    ) -> str:
        """Get AI response using streaming endpoint.

        On failure, retries ONCE with a fresh chat session. The `_is_retry`
        guard prevents recursive cascading — if the retry itself fails, a
        fallback string is returned immediately.
        """
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

            if _is_retry:
                # Already on the single allowed retry — do not recurse further.
                logger.error("Retry also failed; returning fallback response.")
                return "I'm having trouble processing your request."

            try:
                # One retry with a fresh session (guards against session-
                # specific issues without cascading on systemic failures).
                new_session_uuid = await self.create_chat_session()
                return await self.get_response(
                    new_session_uuid, message, context, _is_retry=True
                )
            except Exception as retry_error:
                logger.error(f"Retry failed: {retry_error}")
                return "I'm having trouble processing your request."

    async def fetch_session_messages(self, session_uuid: str) -> list:
        """Fetch all messages for a session, including citation data.

        Used after a streaming response completes to retrieve the
        ``cite_data_json`` field from the most recent assistant message.
        The streaming endpoint does not include citation metadata, so this
        separate GET call is the only way to obtain it.

        Args:
            session_uuid: The UUID of the chat session.

        Returns:
            A list of message dicts. Each dict may contain a
            ``cite_data_json`` field with citation metadata.
        """
        try:
            endpoint = f'session/{session_uuid}/messages'
            response = await self._make_request('GET', endpoint)
            # The API may return a list directly or wrap it in a dict.
            # Normalize to always return a list.
            if isinstance(response, list):
                return response
            if isinstance(response, dict) and 'data' in response:
                return response['data']
            # Fallback: wrap single dict in a list
            return [response] if response else []
        except Exception as e:
            logger.error(f"Failed to fetch session messages: {e}")
            return []

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