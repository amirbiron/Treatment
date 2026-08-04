"""
Schedule helpers for interval-based reminders ("every X hours").

An interval is stored the same way a fixed daily time is: as a set of
MedicineSchedule rows. "Every 8 hours from 07:00" simply becomes 07:00, 15:00
and 23:00, so the scheduler, the reports and the dose log all keep working
without knowing that an interval was involved.

Only divisors of 24 are offered. With anything else the pattern cannot repeat
daily - "every 5 hours from 08:00" would give 08:00, 13:00, 18:00, 23:00 and
then a 9 hour gap before the next day starts, which is not what "every 5 hours"
means. Real dosing intervals are divisors of 24 anyway.
"""

from dataclasses import dataclass
from datetime import time
from typing import List, Optional

# Offered intervals, in hours. Every entry must divide 24 exactly.
INTERVAL_HOURS_CHOICES = (2, 3, 4, 6, 8, 12)

MINUTES_PER_DAY = 24 * 60


def is_supported_interval(interval_hours) -> bool:
    """Whether an interval can be turned into a daily schedule."""
    return interval_hours in INTERVAL_HOURS_CHOICES


def expand_interval_times(start: time, interval_hours: int) -> List[time]:
    """Return the daily times for taking a medicine every `interval_hours` hours.

    The returned list is sorted and covers exactly one day, so it repeats
    cleanly: expand_interval_times(time(7, 0), 8) -> [07:00, 15:00, 23:00].
    """
    if interval_hours not in INTERVAL_HOURS_CHOICES:
        raise ValueError(f"Unsupported interval: {interval_hours} hours")

    doses_per_day = 24 // interval_hours
    start_minutes = start.hour * 60 + start.minute

    times = []
    for i in range(doses_per_day):
        minutes = (start_minutes + i * interval_hours * 60) % MINUTES_PER_DAY
        times.append(time(hour=minutes // 60, minute=minutes % 60))

    return sorted(times)


def format_times(times: List[time]) -> str:
    """Render schedule times for a message, e.g. '07:00, 15:00, 23:00'."""
    return ", ".join(t.strftime("%H:%M") for t in sorted(times))


def describe_interval(start: time, interval_hours: int) -> str:
    """Hebrew summary of an interval schedule, including the expanded times."""
    times = expand_interval_times(start, interval_hours)
    return f"כל {interval_hours} שעות (החל מ-{start.strftime('%H:%M')}): {format_times(times)}"


# --- Callback parsing -------------------------------------------------------
#
# The interval buttons deliberately reuse the ``time_`` prefix so the existing
# conversation state and the main callback chain route them with no new
# registrations. That makes the order in which the variants are recognised
# load-bearing: ``time_ivl_back`` also starts with ``time_ivl_``, and
# ``time_ivlstart_8_07_00`` also starts with ``time_``. Both the add flow and the
# edit flow parse the same strings, so the order lives here once rather than in
# two if-chains that could drift apart.

MENU = "menu"  # open the interval picker
BACK = "back"  # return to the plain time keyboard
PICK = "pick"  # an interval was chosen, ask for a start time
CUSTOM = "custom"  # start time will be typed in
START = "start"  # start time was chosen, the schedule is complete
INVALID = "invalid"  # interval-shaped but unusable, e.g. a stale button


@dataclass(frozen=True)
class IntervalCallback:
    """A parsed ``time_*`` interval button press."""

    kind: str
    interval_hours: Optional[int] = None
    start_time: Optional[time] = None


def _parse_hours(raw: str) -> Optional[int]:
    """Interval hours from callback data, or None if unusable."""
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return None
    return hours if is_supported_interval(hours) else None


def parse_interval_callback(data: str) -> Optional[IntervalCallback]:
    """Classify an interval callback, or return None if it is not one.

    Values are validated here so that an unsupported interval never reaches
    user state or expand_interval_times: callers get INVALID and can say
    something specific instead of falling through to a generic error.
    """
    if data == "time_interval":
        return IntervalCallback(MENU)

    if data == "time_ivl_back":
        return IntervalCallback(BACK)

    if data.startswith("time_ivlcustom_"):
        hours = _parse_hours(data[len("time_ivlcustom_"):])
        return IntervalCallback(CUSTOM, hours) if hours else IntervalCallback(INVALID)

    if data.startswith("time_ivlstart_"):
        parts = data[len("time_ivlstart_"):].split("_")
        if len(parts) != 3:
            return IntervalCallback(INVALID)
        hours = _parse_hours(parts[0])
        if not hours:
            return IntervalCallback(INVALID)
        try:
            start = time(hour=int(parts[1]), minute=int(parts[2]))
        except ValueError:
            return IntervalCallback(INVALID)
        return IntervalCallback(START, hours, start)

    if data.startswith("time_ivl_"):
        hours = _parse_hours(data[len("time_ivl_"):])
        return IntervalCallback(PICK, hours) if hours else IntervalCallback(INVALID)

    return None
