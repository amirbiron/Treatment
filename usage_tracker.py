"""
Daily API usage tracker with automatic reset and threshold alerts.
Tracks Gemini API calls to prevent exceeding daily limits.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)

# Configurable limits
DAILY_LIMIT = 1500
ALERT_THRESHOLD = 1000

# In-memory state
_today = date.today()
_count = 0


def increment_and_check_usage() -> int:
    """Increment usage counter and return current count. Resets daily."""
    global _today, _count
    now = date.today()
    if now != _today:
        logger.info(f"Usage tracker reset (yesterday: {_count} calls)")
        _today = now
        _count = 0
    _count += 1
    return _count


def get_usage() -> int:
    """Get current daily usage count."""
    global _today, _count
    if date.today() != _today:
        return 0
    return _count


def is_limit_reached() -> bool:
    """Check if daily limit has been reached."""
    return get_usage() >= DAILY_LIMIT
