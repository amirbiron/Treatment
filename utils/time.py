"""
Timezone-aware utilities for scheduling and time normalization.

This module centralizes timezone handling to avoid naive vs aware mistakes
and to ensure consistent behavior across DST changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

import pytz


# Default timezone if user does not have a timezone set
DEFAULT_TZ_NAME: str = "Asia/Jerusalem"


def get_timezone(tz: Optional[Union[str, "pytz.tzinfo.BaseTzInfo"]]) -> "pytz.tzinfo.BaseTzInfo":
    """
    Resolve a timezone input (name or tzinfo) to a pytz timezone object.
    Falls back to DEFAULT_TZ_NAME if tz is None/empty/invalid.
    """
    if tz is None:
        return pytz.timezone(DEFAULT_TZ_NAME)
    if not isinstance(tz, str):
        # Assume tzinfo-like
        return tz  # type: ignore[return-value]
    name = (tz or "").strip() or DEFAULT_TZ_NAME
    try:
        return pytz.timezone(name)
    except Exception:
        return pytz.timezone(DEFAULT_TZ_NAME)


def get_user_timezone_name(user) -> str:
    """
    Return the configured timezone name for a user, or DEFAULT_TZ_NAME if missing.
    The user object is expected to have a 'timezone' attribute (string or None).
    """
    tz = getattr(user, "timezone", None)
    if isinstance(tz, str) and tz.strip():
        # Treat plain "UTC" as not-set default for backwards-compat
        if tz.strip().upper() == "UTC":
            return DEFAULT_TZ_NAME
        return tz.strip()
    return DEFAULT_TZ_NAME


def ensure_aware(dt: datetime, tz: Optional[Union[str, "pytz.tzinfo.BaseTzInfo"]] = None) -> datetime:
    """
    Ensure a datetime is timezone-aware in the given timezone.

    - If dt is naive, localize it to tz (or DEFAULT_TZ_NAME).
    - If dt is aware but different tz, convert to tz.
    - If dt is already aware in tz, return as-is.
    """
    tzinfo = get_timezone(tz)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        # Localize naive datetime to tz
        return tzinfo.localize(dt)
    # Convert to requested tz
    return dt.astimezone(tzinfo)


def now_in_timezone(tz: Optional[Union[str, "pytz.tzinfo.BaseTzInfo"]] = None) -> datetime:
    """
    Current time as an aware datetime in the given timezone (or DEFAULT_TZ_NAME).
    """
    tzinfo = get_timezone(tz)
    return datetime.now(tzinfo)

