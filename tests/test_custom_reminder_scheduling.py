"""Scheduling tests for standalone reminders, against a real APScheduler."""

from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scheduler import MedicineScheduler


def _reminder(**kwargs):
    r = MagicMock()
    r.id = kwargs.get("id", 1)
    r.user_id = kwargs.get("user_id", 11)
    r.text = kwargs.get("text", "לקחת מרשם")
    r.repeat = kwargs.get("repeat", "once")
    r.remind_at = kwargs.get("remind_at")
    r.remind_time = kwargs.get("remind_time")
    r.weekday = kwargs.get("weekday")
    r.is_active = kwargs.get("is_active", True)
    return r


@pytest.fixture
def sched():
    return MedicineScheduler()


@pytest.fixture
def no_db_user():
    """The scheduler looks the user up for their timezone; None falls back to the default."""
    return patch("scheduler.DatabaseManager.get_user_by_id", AsyncMock(return_value=None))


def _job(sched, user_id=11, reminder_id=1):
    return sched.scheduler.get_job(f"custom_reminder_{user_id}_{reminder_id}")


@pytest.mark.asyncio
async def test_daily_reminder_creates_a_cron_job(sched, no_db_user):
    with no_db_user:
        job_id = await sched.schedule_custom_reminder(_reminder(repeat="daily", remind_time=time(8, 30)))

    assert job_id == "custom_reminder_11_1"
    trigger = str(_job(sched).trigger)
    assert "hour='8'" in trigger and "minute='30'" in trigger


@pytest.mark.asyncio
async def test_weekly_reminder_pins_the_weekday(sched, no_db_user):
    with no_db_user:
        await sched.schedule_custom_reminder(_reminder(repeat="weekly", remind_time=time(7, 0), weekday=6))

    trigger = str(_job(sched).trigger)
    assert "day_of_week='6'" in trigger
    assert "hour='7'" in trigger


@pytest.mark.asyncio
async def test_future_one_off_is_armed(sched, no_db_user):
    future = datetime.now() + timedelta(days=2)
    with no_db_user:
        job_id = await sched.schedule_custom_reminder(_reminder(repeat="once", remind_at=future))

    assert job_id == "custom_reminder_11_1"
    assert _job(sched) is not None


@pytest.mark.asyncio
async def test_past_one_off_is_refused(sched, no_db_user):
    """Arming a past date would fire immediately or never; say so instead."""
    past = datetime.now() - timedelta(days=1)
    with no_db_user:
        job_id = await sched.schedule_custom_reminder(_reminder(repeat="once", remind_at=past))

    assert job_id is None
    assert _job(sched) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"repeat": "once", "remind_at": None},
        {"repeat": "daily", "remind_time": None},
        {"repeat": "weekly", "remind_time": time(8, 0), "weekday": None},
        {"repeat": "weekly", "remind_time": None, "weekday": 3},
        {"repeat": "monthly", "remind_time": time(8, 0)},
    ],
)
async def test_incomplete_reminders_are_refused_not_crashed(sched, no_db_user, kwargs):
    with no_db_user:
        assert await sched.schedule_custom_reminder(_reminder(**kwargs)) is None
    assert _job(sched) is None


@pytest.mark.asyncio
async def test_cancelling_removes_only_that_job(sched, no_db_user):
    with no_db_user:
        await sched.schedule_custom_reminder(_reminder(id=1, repeat="daily", remind_time=time(8, 0)))
        await sched.schedule_custom_reminder(_reminder(id=2, repeat="daily", remind_time=time(9, 0)))
        await sched.cancel_custom_reminder(11, 1)

    assert _job(sched, reminder_id=1) is None
    assert _job(sched, reminder_id=2) is not None


@pytest.mark.asyncio
async def test_medicine_cancellation_leaves_custom_reminders_alone(sched, no_db_user):
    """cancel_medicine_reminders sweeps by prefix; custom jobs must not be caught."""
    with no_db_user:
        await sched.schedule_custom_reminder(_reminder(repeat="daily", remind_time=time(8, 0)))
        await sched.schedule_medicine_reminder(user_id=11, medicine_id=3, reminder_time=time(9, 0))
        await sched.cancel_medicine_reminders(11, 3)

    assert _job(sched) is not None, "the custom reminder was swept away with the medicine's"


# --- delivery ------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_off_is_retired_after_it_fires(sched):
    """Otherwise a spent one-off lingers in the list forever."""
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()
    user = MagicMock()
    user.telegram_id = 7
    user.is_active = True

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=_reminder(repeat="once", text="לקחת מרשם"))
        db.get_user_by_id = AsyncMock(return_value=user)
        db.set_custom_reminder_active = AsyncMock()
        await sched._send_custom_reminder(11, 1)

    assert "לקחת מרשם" in sched.bot.send_message.call_args.kwargs["text"]
    db.set_custom_reminder_active.assert_awaited_once_with(1, False)


@pytest.mark.asyncio
async def test_a_repeating_reminder_stays_active_after_firing(sched):
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()
    user = MagicMock()
    user.telegram_id = 7
    user.is_active = True

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=_reminder(repeat="daily", remind_time=time(8, 0)))
        db.get_user_by_id = AsyncMock(return_value=user)
        db.set_custom_reminder_active = AsyncMock()
        await sched._send_custom_reminder(11, 1)

    db.set_custom_reminder_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deactivated_reminder_does_not_send(sched):
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=_reminder(is_active=False))
        db.get_user_by_id = AsyncMock(return_value=MagicMock())
        await sched._send_custom_reminder(11, 1)

    sched.bot.send_message.assert_not_awaited()


# --- restart recovery ----------------------------------------------------


@pytest.mark.asyncio
async def test_restart_rearms_repeating_and_retires_stale_one_offs(sched, no_db_user):
    """Render restarts often; what survives a restart is what the user actually gets."""
    live = _reminder(id=1, repeat="daily", remind_time=time(8, 0))
    future = _reminder(id=2, repeat="once", remind_at=datetime.now() + timedelta(days=1))
    stale = _reminder(id=3, repeat="once", remind_at=datetime.now() - timedelta(days=1))

    with no_db_user, patch("scheduler.DatabaseManager") as db:
        db.get_user_by_id = AsyncMock(return_value=None)
        db.get_all_active_custom_reminders = AsyncMock(return_value=[live, future, stale])
        db.set_custom_reminder_active = AsyncMock()
        await sched._reschedule_all_custom_reminders()

    assert _job(sched, reminder_id=1) is not None
    assert _job(sched, reminder_id=2) is not None
    assert _job(sched, reminder_id=3) is None
    db.set_custom_reminder_active.assert_awaited_once_with(3, False)
