"""
Shared pytest configuration and fixtures for the Discord bot test suite.

The config module (config.py) executes BotConfig.from_env() at import time,
which means any module that transitively imports `config` will fail if the
required env vars are not set. We set dummy values here so that imports
succeed in all test modules.
"""

import os
import sys

# Ensure the project root is on sys.path so that `import config`, etc. work.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Set required env vars BEFORE any application module is imported.
# These are dummy values used solely to satisfy config.py's from_env() check.
_REQUIRED_ENV_DEFAULTS = {
    "DISCORD_TOKEN": "test-discord-token",
    "GPT_TRAINER_TOKEN": "test-gpt-trainer-token",
    "CHATBOT_UUID": "test-chatbot-uuid",
    "GOOGLE_API_KEY": "test-google-api-key",
}

for key, value in _REQUIRED_ENV_DEFAULTS.items():
    os.environ.setdefault(key, value)
