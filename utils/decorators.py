"""
Location: /mnt/f/Code/discordbot/utils/decorators.py
Summary: Reusable decorators for the Discord bot.
         Contains error handling and other function wrappers.

Used by: main.py to wrap async command handlers with consistent error logging.
"""

import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


def with_error_handling(func: Callable) -> Callable:
    """Decorator to handle errors in async functions.

    Wraps an async function to catch any exceptions, log them with full
    traceback information, and re-raise. This ensures errors are always
    logged consistently while allowing the caller to handle them.

    Args:
        func: The async function to wrap.

    Returns:
        Wrapped async function with error logging.

    Example:
        @with_error_handling
        async def my_command(interaction):
            # If this raises, error is logged before propagating
            await risky_operation()
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
            raise
    return wrapper
