"""Tests for main._apply_schedule_times.

This is the single place that writes a medicine's schedule and re-arms its
reminders, so the ordering matters: the stored times must not be replaced
unless there is a user to schedule them for.
"""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main


@pytest.fixture
def bot():
    return main.MedicineReminderBot.__new__(main.MedicineReminderBot)


@pytest.fixture
def user():
    u = MagicMock()
    u.id = 11
    u.timezone = "Asia/Jerusalem"
    return u


def _patches(user_return):
    return (
        patch.object(main.DatabaseManager, "get_user_by_telegram_id", AsyncMock(return_value=user_return)),
        patch.object(main.DatabaseManager, "replace_medicine_schedules", AsyncMock()),
        patch.object(main.medicine_scheduler, "cancel_medicine_reminders", AsyncMock()),
        patch.object(main.medicine_scheduler, "schedule_medicine_reminder", AsyncMock()),
    )


@pytest.mark.asyncio
async def test_arms_one_reminder_per_time(bot, user):
    get_user, replace, cancel, schedule = _patches(user)
    times = [time(7, 0), time(15, 0), time(23, 0)]
    with get_user, replace as replace_m, cancel as cancel_m, schedule as schedule_m:
        await bot._apply_schedule_times(7, 3, times)

    replace_m.assert_awaited_once_with(3, times)
    cancel_m.assert_awaited_once_with(11, 3)
    assert [c.kwargs["reminder_time"] for c in schedule_m.await_args_list] == times
    assert all(c.kwargs["user_id"] == 11 for c in schedule_m.await_args_list)


@pytest.mark.asyncio
async def test_unknown_user_aborts_before_touching_the_schedule(bot):
    """Replacing first would leave stored times with no reminders behind them."""
    get_user, replace, cancel, schedule = _patches(None)
    with get_user, replace as replace_m, cancel as cancel_m, schedule as schedule_m:
        with pytest.raises(ValueError):
            await bot._apply_schedule_times(7, 3, [time(8, 0)])

    replace_m.assert_not_awaited()
    cancel_m.assert_not_awaited()
    schedule_m.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_bad_time_does_not_cost_the_others(bot, user, caplog):
    """A failure on one dose must still arm the rest, and must be logged by time."""
    get_user, replace, cancel, _ = _patches(user)
    times = [time(7, 0), time(15, 0), time(23, 0)]

    async def flaky(**kwargs):
        if kwargs["reminder_time"] == time(15, 0):
            raise RuntimeError("scheduler said no")

    with get_user, replace, cancel, patch.object(
        main.medicine_scheduler, "schedule_medicine_reminder", AsyncMock(side_effect=flaky)
    ) as schedule_m:
        with pytest.raises(RuntimeError):
            await bot._apply_schedule_times(7, 3, times)

    # every time was attempted, not just the ones before the failure
    assert [c.kwargs["reminder_time"] for c in schedule_m.await_args_list] == times
    assert "15:00" in caplog.text
    assert "scheduler said no" in caplog.text


@pytest.mark.asyncio
async def test_a_partial_failure_is_reported_rather_than_passing_silently(bot, user):
    get_user, replace, cancel, _ = _patches(user)

    async def flaky(**kwargs):
        if kwargs["reminder_time"] == time(23, 0):
            raise RuntimeError("nope")

    with get_user, replace, cancel, patch.object(
        main.medicine_scheduler, "schedule_medicine_reminder", AsyncMock(side_effect=flaky)
    ):
        with pytest.raises(RuntimeError, match="23:00"):
            await bot._apply_schedule_times(7, 3, [time(7, 0), time(23, 0)])


@pytest.mark.asyncio
async def test_falls_back_to_the_default_timezone(bot):
    u = MagicMock()
    u.id = 11
    u.timezone = None
    get_user, replace, cancel, schedule = _patches(u)
    with get_user, replace, cancel, schedule as schedule_m:
        await bot._apply_schedule_times(7, 3, [time(8, 0)])

    assert schedule_m.await_args.kwargs["timezone"] == main.config.DEFAULT_TIMEZONE
