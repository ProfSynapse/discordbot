"""
Configuration management module for the Discord bot.
Provides a type-safe configuration class that loads settings from environment variables.

Required environment variables:
- DISCORD_TOKEN: Discord bot authentication token
- GPT_TRAINER_TOKEN: Authentication token for GPT Trainer API
- CHATBOT_UUID: UUID of the chatbot instance

Optional environment variables:
- LOG_LEVEL: Logging level (default: INFO)
"""

from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class BotConfig:
    """
    Configuration container for the Discord bot.
    Provides type hints and validation for all configuration values.
    
    Use BotConfig.from_env() to create an instance from environment variables.
    """
    
    # Required parameters
    DISCORD_TOKEN: str  # Discord bot authentication token
    GPT_TRAINER_TOKEN: str  # GPT Trainer API authentication token
    CHATBOT_UUID: str  # Unique identifier for the chatbot instance
    GOOGLE_API_KEY: str  # Google API key for Imagen
    
    # Optional parameters for content scheduling
    CONTENT_CHANNEL_ID: Optional[int] = None  # Discord channel ID for automated content (news + YouTube)
    YOUTUBE_API_KEY: Optional[str] = None  # YouTube API key (optional)
    OPENAI_API_KEY: Optional[str] = None  # OpenAI API key for DALL-E (deprecated)
    IMAGE_GALLERY_CHANNEL_ID: Optional[int] = None  # Discord channel ID for cross-posting generated images

    # Session management configuration
    SESSION_DB_PATH: str = '/data/sessions.db'  # SQLite database path on Railway volume
    SESSION_MAX_AGE_DAYS: int = 0  # Auto-cleanup disabled (0 = never expire). Set to positive number to enable.
    USE_CHANNEL_CONTEXT: bool = True  # Include other users' messages as context
    CHANNEL_CONTEXT_LIMIT: int = 10  # Number of recent messages to include

    # Optional parameters with defaults
    LOG_LEVEL: str = 'INFO'  # Logging level (INFO, DEBUG, etc.)
    MAX_MESSAGE_LENGTH: int = 2000  # Maximum Discord message length
    MAX_HISTORY_MESSAGES: int = 50  # Number of messages to keep in history
    RATE_LIMIT_DELAY: float = 1.0  # Delay between API requests
    CONVERSATION_HISTORY_FILE: str = 'conversation_history.json'  # Path to conversation history storage

    @classmethod
    def from_env(cls) -> 'BotConfig':
        """
        Create a configuration instance from environment variables.

        Returns:
            BotConfig: Configuration instance

        Raises:
            EnvironmentError: If required environment variables are missing
        """
        # Validate all required environment variables upfront
        required_vars = ['DISCORD_TOKEN', 'GPT_TRAINER_TOKEN', 'CHATBOT_UUID', 'GOOGLE_API_KEY']
        missing = [var for var in required_vars if var not in os.environ]

        if missing:
            raise EnvironmentError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Please set all of the following: {', '.join(required_vars)}"
            )

        return cls(
            DISCORD_TOKEN=os.environ['DISCORD_TOKEN'],
            GPT_TRAINER_TOKEN=os.environ['GPT_TRAINER_TOKEN'],
            CHATBOT_UUID=os.environ['CHATBOT_UUID'],
            GOOGLE_API_KEY=os.environ['GOOGLE_API_KEY'],
            CONTENT_CHANNEL_ID=int(os.environ['CONTENT_CHANNEL_ID']) if 'CONTENT_CHANNEL_ID' in os.environ else None,
            YOUTUBE_API_KEY=os.environ.get('YOUTUBE_API_KEY'),
            OPENAI_API_KEY=os.environ.get('OPENAI_API_KEY'),
            IMAGE_GALLERY_CHANNEL_ID=int(os.environ['IMAGE_GALLERY_CHANNEL_ID']) if 'IMAGE_GALLERY_CHANNEL_ID' in os.environ else None,
            SESSION_DB_PATH=os.environ.get('SESSION_DB_PATH', '/data/sessions.db'),
            SESSION_MAX_AGE_DAYS=int(os.environ.get('SESSION_MAX_AGE_DAYS', '0')),
            USE_CHANNEL_CONTEXT=os.environ.get('USE_CHANNEL_CONTEXT', 'true').lower() == 'true',
            CHANNEL_CONTEXT_LIMIT=int(os.environ.get('CHANNEL_CONTEXT_LIMIT', '10')),
            LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),
            MAX_MESSAGE_LENGTH=int(os.environ.get('MAX_MESSAGE_LENGTH', '2000')),
            MAX_HISTORY_MESSAGES=int(os.environ.get('MAX_HISTORY_MESSAGES', '100')),
            RATE_LIMIT_DELAY=float(os.environ.get('RATE_LIMIT_DELAY', '1.0')),
            CONVERSATION_HISTORY_FILE=os.environ.get('CONVERSATION_HISTORY_FILE', 'conversation_history.json')
        )

config = BotConfig.from_env()
