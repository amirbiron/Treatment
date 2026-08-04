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

from datetime import time
from typing import List

# Offered intervals, in hours. Every entry must divide 24 exactly.
INTERVAL_HOURS_CHOICES = (2, 3, 4, 6, 8, 12)

MINUTES_PER_DAY = 24 * 60


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
