"""Tests for standalone (non-medicine) reminders: creation flow and scheduling."""

from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.custom_reminder_handler import (
    WEEKDAY_NAMES,
    CustomReminderHandler,
    describe_reminder,
)


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


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
def handler():
    return CustomReminderHandler()


@pytest.fixture
def ctx():
    c = MagicMock()
    c.user_data = {}
    return c


def _query(data):
    q = MagicMock()
    q.data = data
    q.from_user.id = 7
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


def _callback_update(data):
    u = MagicMock()
    u.effective_user.id = 7
    u.callback_query = _query(data)
    return u


def _text_update(text):
    u = MagicMock()
    u.effective_user.id = 7
    u.callback_query = None
    u.message.text = text
    u.message.reply_text = AsyncMock()
    return u


def _user():
    u = MagicMock()
    u.id = 11
    u.timezone = "Asia/Jerusalem"
    return u


# --- description ---------------------------------------------------------


def test_describes_a_one_off():
    r = _reminder(repeat="once", remind_at=datetime(2026, 9, 1, 10, 30))
    assert describe_reminder(r) == "פעם אחת, 01/09/2026 10:30"


def test_describes_a_daily():
    assert describe_reminder(_reminder(repeat="daily", remind_time=time(8, 0))) == "כל יום ב-08:00"


def test_describes_a_weekly():
    r = _reminder(repeat="weekly", remind_time=time(7, 30), weekday=6)
    assert describe_reminder(r) == "כל יום ראשון ב-07:30"


def test_weekday_names_follow_apscheduler_numbering():
    """APScheduler's day_of_week is 0=Monday..6=Sunday; a mismatch fires on the wrong day."""
    assert len(WEEKDAY_NAMES) == 7
    assert WEEKDAY_NAMES[0] == "שני"  # Monday
    assert WEEKDAY_NAMES[6] == "ראשון"  # Sunday
    # python's date.weekday() uses the same numbering, so the day picker agrees
    monday = date(2026, 8, 3)
    assert monday.weekday() == 0


# --- creation flow -------------------------------------------------------


@pytest.mark.asyncio
async def test_text_step_claims_the_message_and_asks_how_often(handler, ctx):
    await handler.start_add(_callback_update("crem_add"), ctx)
    assert ctx.user_data["awaiting_custom_reminder_text"] is True

    update = _text_update("לקחת מרשם מהרופא")
    claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    assert ctx.user_data["custom_reminder_draft"]["text"] == "לקחת מרשם מהרופא"
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert set(_callbacks(markup)) >= {"crem_rep_once", "crem_rep_daily", "crem_rep_weekly"}


@pytest.mark.asyncio
async def test_unrelated_text_is_not_claimed(handler, ctx):
    assert await handler.handle_text(_text_update("שלום"), ctx) is False


@pytest.mark.asyncio
async def test_overlong_text_is_truncated_not_rejected(handler, ctx):
    ctx.user_data["awaiting_custom_reminder_text"] = True
    await handler.handle_text(_text_update("א" * 500), ctx)
    assert len(ctx.user_data["custom_reminder_draft"]["text"]) == 300


@pytest.mark.asyncio
async def test_daily_skips_straight_to_the_time(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "למדוד לחץ דם"}
    update = _callback_update("crem_rep_daily")
    await handler.pick_repeat(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert any(c.startswith("crem_time_") for c in _callbacks(markup))


@pytest.mark.asyncio
async def test_weekly_asks_for_a_weekday_first(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "שקילה"}
    update = _callback_update("crem_rep_weekly")
    await handler.pick_repeat(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert [c for c in _callbacks(markup) if c.startswith("crem_wd_")] == [
        f"crem_wd_{i}" for i in range(7)
    ]


@pytest.mark.asyncio
async def test_one_off_offers_relative_days_so_buttons_never_go_stale(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "לקחת מרשם"}
    update = _callback_update("crem_rep_once")
    with patch("handlers.custom_reminder_handler.DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        await handler.pick_repeat(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    days = [c for c in _callbacks(markup) if c.startswith("crem_day_")]
    assert days == [f"crem_day_{i}" for i in range(7)]


@pytest.mark.asyncio
async def test_a_lost_draft_is_reported_rather_than_crashing(handler, ctx):
    """user_data is cleared on restart; a stale keyboard must not explode."""
    for data, method in [
        ("crem_rep_daily", "pick_repeat"),
        ("crem_day_1", "pick_day"),
        ("crem_wd_3", "pick_weekday"),
        ("crem_time_08_00", "pick_time"),
    ]:
        update = _callback_update(data)
        await getattr(handler, method)(update, ctx)
        assert "פגה" in update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_daily_reminder_is_saved_and_armed(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "למדוד לחץ דם", "repeat": "daily"}
    update = _callback_update("crem_time_08_00")

    saved = _reminder(repeat="daily", remind_time=time(8, 0), text="למדוד לחץ דם")
    with patch("handlers.custom_reminder_handler.DatabaseManager") as db, patch(
        "handlers.custom_reminder_handler.medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.create_custom_reminder = AsyncMock(return_value=saved)
        sched.schedule_custom_reminder = AsyncMock(return_value="job-1")
        await handler.pick_time(update, ctx)

    kwargs = db.create_custom_reminder.await_args.kwargs
    assert kwargs["repeat"] == "daily"
    assert kwargs["remind_time"] == time(8, 0)
    assert kwargs["remind_at"] is None
    sched.schedule_custom_reminder.assert_awaited_once_with(saved)
    assert "custom_reminder_draft" not in ctx.user_data


@pytest.mark.asyncio
async def test_weekly_reminder_carries_the_weekday(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "שקילה", "repeat": "weekly", "weekday": 6}
    update = _callback_update("crem_time_07_00")

    with patch("handlers.custom_reminder_handler.DatabaseManager") as db, patch(
        "handlers.custom_reminder_handler.medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.create_custom_reminder = AsyncMock(return_value=_reminder(repeat="weekly"))
        sched.schedule_custom_reminder = AsyncMock(return_value="job-1")
        await handler.pick_time(update, ctx)

    kwargs = db.create_custom_reminder.await_args.kwargs
    assert kwargs["repeat"] == "weekly"
    assert kwargs["weekday"] == 6
    assert kwargs["remind_time"] == time(7, 0)


@pytest.mark.asyncio
async def test_one_off_resolves_the_chosen_day_into_a_datetime(handler, ctx):
    ctx.user_data["custom_reminder_draft"] = {"text": "לקחת מרשם", "repeat": "once", "days_ahead": 2}
    update = _callback_update("crem_time_10_00")

    with patch("handlers.custom_reminder_handler.DatabaseManager") as db, patch(
        "handlers.custom_reminder_handler.medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.create_custom_reminder = AsyncMock(return_value=_reminder())
        sched.schedule_custom_reminder = AsyncMock(return_value="job-1")
        await handler.pick_time(update, ctx)

    remind_at = db.create_custom_reminder.await_args.kwargs["remind_at"]
    assert remind_at.time() == time(10, 0)
    assert remind_at.date() >= date.today()  # two days ahead in the user's tz
    assert db.create_custom_reminder.await_args.kwargs["remind_time"] is None


@pytest.mark.asyncio
async def test_a_past_one_off_is_retired_not_left_dangling(handler, ctx):
    """schedule_custom_reminder returns None for a moment that already passed."""
    ctx.user_data["custom_reminder_draft"] = {"text": "מאוחר מדי", "repeat": "once", "days_ahead": 0}
    update = _callback_update("crem_time_06_00")

    saved = _reminder(id=9)
    with patch("handlers.custom_reminder_handler.DatabaseManager") as db, patch(
        "handlers.custom_reminder_handler.medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.create_custom_reminder = AsyncMock(return_value=saved)
        db.set_custom_reminder_active = AsyncMock()
        sched.schedule_custom_reminder = AsyncMock(return_value=None)
        await handler.pick_time(update, ctx)

    db.set_custom_reminder_active.assert_awaited_once_with(9, False)
    assert "כבר עבר" in update.callback_query.edit_message_text.call_args.args[0]


# --- deletion ------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_cancels_the_job_before_removing_the_row(handler, ctx):
    update = _callback_update("cremdel_9_confirm")
    order = []

    with patch("handlers.custom_reminder_handler.DatabaseManager") as db, patch(
        "handlers.custom_reminder_handler.medicine_scheduler"
    ) as sched:
        db.get_custom_reminder_by_id = AsyncMock(return_value=_reminder(id=9, user_id=11))
        db.delete_custom_reminder = AsyncMock(side_effect=lambda *a: order.append("delete"))
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_user_custom_reminders = AsyncMock(return_value=[])
        sched.cancel_custom_reminder = AsyncMock(side_effect=lambda *a: order.append("cancel"))
        await handler.confirm_delete(update, ctx)

    assert order == ["cancel", "delete"], "a live job would outlive its row"
    sched.cancel_custom_reminder.assert_awaited_once_with(11, 9)


@pytest.mark.asyncio
async def test_cancelling_delete_keeps_the_reminder(handler, ctx):
    update = _callback_update("cremdel_9_cancel")
    with patch("handlers.custom_reminder_handler.DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_user_custom_reminders = AsyncMock(return_value=[_reminder(id=9)])
        db.delete_custom_reminder = AsyncMock()
        await handler.cancel_delete(update, ctx)

    db.delete_custom_reminder.assert_not_awaited()


def test_every_button_the_handler_emits_is_registered(handler):
    patterns = [h.pattern for h in handler.get_handlers()]
    emitted = [
        "crem_menu", "crem_add", "crem_rep_once", "crem_rep_daily", "crem_rep_weekly",
        "crem_wd_0", "crem_wd_6", "crem_day_0", "crem_day_6", "crem_time_08_00",
        "crem_del_1", "cremdel_1_confirm", "cremdel_1_cancel",
    ]
    for data in emitted:
        assert any(p.match(data) for p in patterns), f"{data} has no handler"
