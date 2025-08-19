"""
Time utilities: timezone handling and normalization for scheduling.

This module centralizes conversion to timezone-aware datetimes and default
timezone selection. It avoids surprises with naive datetimes and respects DST.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time
from typing import Optional

import pytz


DEFAULT_TZ_NAME = "Asia/Jerusalem"


def get_timezone(tz_name: Optional[str]) -> "pytz.tzinfo.BaseTzInfo":
    """Return tzinfo for a given timezone name; fallback to Asia/Jerusalem.

    Accepts None or invalid names; in both cases falls back to the default.
    """
    if isinstance(tz_name, str):
        try:
            return pytz.timezone(tz_name)
        except Exception:
            pass
    return pytz.timezone(DEFAULT_TZ_NAME)


def ensure_aware(dt: datetime, tz_name: Optional[str] = None) -> datetime:
    """Ensure a datetime is timezone-aware in the specified timezone.

    - If dt is naive: localize it to the given tz (or default).
    - If dt is aware: convert to the given tz (or default) if provided.
    """
    tz = get_timezone(tz_name)
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        # Localize naive datetime to the timezone
        return tz.localize(dt)
    # Convert to desired timezone
    return dt.astimezone(tz)


def build_local_datetime_for_time(local_time: dt_time, tz_name: Optional[str] = None, *, now: Optional[datetime] = None) -> datetime:
    """Build a timezone-aware datetime for today at local_time in tz.

    Useful when computing single-run reminders (e.g., snooze) in the user's
    local timezone.
    """
    tz = get_timezone(tz_name)
    ref = ensure_aware(now or datetime.now(), tz_name)
    target_naive = datetime(ref.year, ref.month, ref.day, local_time.hour, local_time.minute, local_time.second)
    return ensure_aware(target_naive, tz.zone)

