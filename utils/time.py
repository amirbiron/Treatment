from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz


DEFAULT_TZ_NAME = "Asia/Jerusalem"


def get_default_timezone_name() -> str:
    """Return the default timezone name used by the bot.

    We avoid relying on environment/config defaults here and enforce
    Asia/Jerusalem as the product default.
    """

    return DEFAULT_TZ_NAME


def get_timezone(tz_name: Optional[str]):
    """Return a tzinfo object for the given timezone name, with safe fallback.

    If tz_name is falsy or invalid, returns Asia/Jerusalem.
    """

    try:
        if not tz_name or not isinstance(tz_name, str) or not tz_name.strip():
            return pytz.timezone(DEFAULT_TZ_NAME)
        return pytz.timezone(tz_name.strip())
    except Exception:
        return pytz.timezone(DEFAULT_TZ_NAME)


def get_user_timezone_name(user: object) -> str:
    """Derive a timezone name string for a user model-like object.

    Prefers user.timezone when present and non-empty; otherwise returns default.
    """

    tz = getattr(user, "timezone", None)
    if isinstance(tz, str) and tz.strip():
        return tz.strip()
    return DEFAULT_TZ_NAME


def ensure_aware(dt: datetime, tz) -> datetime:
    """Ensure a datetime is timezone-aware in the given tz.

    - If dt is naive, localize it to tz (pytz localize if available).
    - If dt is aware, convert it to tz.
    """

    if dt.tzinfo is None:
        # pytz timezones provide localize; fallback to replace if missing
        localize = getattr(tz, "localize", None)
        if callable(localize):
            return localize(dt)
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def now_in_timezone(tz_name: Optional[str] = None) -> datetime:
    """Return current time as timezone-aware datetime in the given tz.

    If tz_name is None, uses the default timezone.
    """

    tz = get_timezone(tz_name or DEFAULT_TZ_NAME)
    return datetime.now(tz)

