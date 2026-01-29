"""
Location: /mnt/f/Code/discordbot/utils/constants.py
Summary: Application-wide constants for the Discord bot.
         Contains limits, configuration values, and static content used across modules.

Used by: main.py for prompt validation and context building.
         Other modules may import these for consistent limit enforcement.
"""

# Maximum number of characters allowed in command prompts sent to external APIs.
MAX_PROMPT_LENGTH = 2000

# Maximum total characters for channel context built from recent messages.
MAX_CONTEXT_CHARS = 2000

# Thinking phrases displayed while the bot processes requests.
# Used to provide visual feedback that the bot is working on a response.
# These include emoji prefixes; main.py wraps them with italic markdown (*...*) for Discord.
THINKING_PHRASES = [
    "Consulting the ancient tomes...",
    "Pondering the mysteries of the universe...",
    "Focusing my neural networks...",
    "Channeling the wisdom of the AI elders...",
    "Weaving threads of knowledge...",
    "Gazing into the crystal GPU...",
    "Speed-reading the internet...",
    "Doing some quick quantum calculations..."
]
