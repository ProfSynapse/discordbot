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
    
    DISCORD_TOKEN: str  # Discord bot authentication token
    GPT_TRAINER_TOKEN: str  # GPT Trainer API authentication token
    CHATBOT_UUID: str  # Unique identifier for the chatbot instance
    LOG_LEVEL: str  # Logging level (INFO, DEBUG, etc.)
    MAX_MESSAGE_LENGTH: int  # Maximum Discord message length
    MAX_HISTORY_MESSAGES: int  # Number of messages to keep in history
    RATE_LIMIT_DELAY: float  # Delay between API requests
    CONVERSATION_HISTORY_FILE: str  # Path to conversation history storage
    NEWS_CHANNEL_ID: int  # Discord channel ID for news articles

    @classmethod
    def from_env(cls) -> 'BotConfig':
        """
        Create a configuration instance from environment variables.
        
        Returns:
            BotConfig: Configuration instance
            
        Raises:
            KeyError: If required environment variables are missing
        """
        return cls(
            DISCORD_TOKEN=os.environ['DISCORD_TOKEN'],
            GPT_TRAINER_TOKEN=os.environ['GPT_TRAINER_TOKEN'],
            CHATBOT_UUID=os.environ['CHATBOT_UUID'],
            LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),
            NEWS_CHANNEL_ID=int(os.environ['NEWS_CHANNEL_ID']),
        )

config = BotConfig.from_env()
