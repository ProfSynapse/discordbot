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
    NEWS_CHANNEL_ID: int  # Discord channel ID for news articles
    
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
            KeyError: If required environment variables are missing
        """
        return cls(
            DISCORD_TOKEN=os.environ['DISCORD_TOKEN'],
            GPT_TRAINER_TOKEN=os.environ['GPT_TRAINER_TOKEN'],
            CHATBOT_UUID=os.environ['CHATBOT_UUID'],
            NEWS_CHANNEL_ID=int(os.environ['NEWS_CHANNEL_ID']),
            LOG_LEVEL=os.environ.get('LOG_LEVEL', 'INFO'),
            MAX_MESSAGE_LENGTH=int(os.environ.get('MAX_MESSAGE_LENGTH', '2000')),
            MAX_HISTORY_MESSAGES=int(os.environ.get('MAX_HISTORY_MESSAGES', '100')),
            RATE_LIMIT_DELAY=float(os.environ.get('RATE_LIMIT_DELAY', '1.0')),
            CONVERSATION_HISTORY_FILE=os.environ.get('CONVERSATION_HISTORY_FILE', 'conversation_history.json')
        )

config = BotConfig.from_env()
