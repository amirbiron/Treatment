"""End-to-end check that an interval produces one live reminder job per dose.

An interval is stored as several MedicineSchedule times, so the scheduler must
end up with one cron job per time - and switching the schedule must leave no
orphaned jobs from the previous one.
"""

from datetime import time
from unittest.mock import AsyncMock, patch

import pytest

from scheduler import MedicineScheduler
from utils.schedule import expand_interval_times


@pytest.fixture
def sched():
    s = MedicineScheduler()
    return s


def _job_times(s, medicine_id):
    """The HHMM suffix of every reminder job for a medicine."""
    return sorted(
        j.id.rsplit("_", 1)[1]
        for j in s.scheduler.get_jobs()
        if j.id.startswith("medicine_reminder_") and j.id.split("_")[3] == str(medicine_id)
    )


async def _schedule_all(s, user_id, medicine_id, times):
    for t in times:
        await s.schedule_medicine_reminder(user_id=user_id, medicine_id=medicine_id, reminder_time=t)


@pytest.mark.asyncio
async def test_interval_creates_one_job_per_dose(sched):
    times = expand_interval_times(time(7, 0), 8)
    with patch("scheduler.DatabaseManager.get_user_by_id", AsyncMock(return_value=None)):
        await _schedule_all(sched, 1, 42, times)

    assert _job_times(sched, 42) == ["0700", "1500", "2300"]


@pytest.mark.asyncio
async def test_switching_interval_leaves_no_orphan_jobs(sched):
    with patch("scheduler.DatabaseManager.get_user_by_id", AsyncMock(return_value=None)):
        await _schedule_all(sched, 1, 42, expand_interval_times(time(7, 0), 8))
        assert len(_job_times(sched, 42)) == 3

        # switch to every 12 hours
        await sched.cancel_medicine_reminders(1, 42)
        await _schedule_all(sched, 1, 42, expand_interval_times(time(8, 0), 12))

    assert _job_times(sched, 42) == ["0800", "2000"], "old 8-hourly jobs should be gone"


@pytest.mark.asyncio
async def test_switching_back_to_a_single_time_clears_the_interval(sched):
    with patch("scheduler.DatabaseManager.get_user_by_id", AsyncMock(return_value=None)):
        await _schedule_all(sched, 1, 42, expand_interval_times(time(6, 0), 6))
        assert len(_job_times(sched, 42)) == 4

        await sched.cancel_medicine_reminders(1, 42)
        await _schedule_all(sched, 1, 42, [time(9, 0)])

    assert _job_times(sched, 42) == ["0900"]


@pytest.mark.asyncio
async def test_other_medicines_are_untouched(sched):
    with patch("scheduler.DatabaseManager.get_user_by_id", AsyncMock(return_value=None)):
        await _schedule_all(sched, 1, 42, expand_interval_times(time(7, 0), 8))
        await _schedule_all(sched, 1, 43, [time(10, 0)])

        await sched.cancel_medicine_reminders(1, 42)

    assert _job_times(sched, 42) == []
    assert _job_times(sched, 43) == ["1000"]
