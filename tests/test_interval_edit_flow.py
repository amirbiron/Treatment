"""Routing tests for the every-X-hours option when editing an existing medicine.

The edit flow lives in main.button_callback, a flat if-chain over ``time_*``
callbacks. These tests pin the dispatch order and, most importantly, that an
interval replaces the schedule with *every* expanded time rather than one.
"""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from utils.keyboards import get_interval_selection_keyboard, get_interval_start_keyboard


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.fixture
def bot():
    b = main.MedicineReminderBot.__new__(main.MedicineReminderBot)
    b._apply_schedule_times = AsyncMock()
    return b


def _query(data):
    q = MagicMock()
    q.data = data
    q.from_user.id = 7
    q.message.chat_id = 7
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


def _update_ctx(data, editing_for=3):
    update = MagicMock()
    update.callback_query = _query(data)
    ctx = MagicMock()
    ctx.user_data = {"editing_schedule_for": editing_for} if editing_for else {}
    return update, ctx


@pytest.mark.asyncio
async def test_interval_entry_offers_the_choices(bot):
    update, ctx = _update_ctx("time_interval")
    await bot.button_callback(update, ctx)
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert _callbacks(markup) == _callbacks(get_interval_selection_keyboard())


@pytest.mark.asyncio
async def test_picking_an_interval_asks_for_a_start_time(bot):
    update, ctx = _update_ctx("time_ivl_8")
    await bot.button_callback(update, ctx)
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert _callbacks(markup) == _callbacks(get_interval_start_keyboard(8))


@pytest.mark.asyncio
async def test_back_is_not_mistaken_for_an_interval(bot):
    update, ctx = _update_ctx("time_ivl_back")
    await bot.button_callback(update, ctx)
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert "time_interval" in _callbacks(markup)


@pytest.mark.asyncio
async def test_interval_replaces_the_schedule_with_every_expanded_time(bot):
    update, ctx = _update_ctx("time_ivlstart_8_07_00")
    med = MagicMock(name="med")
    med.name = "אקמול"
    with patch.object(main.DatabaseManager, "get_medicine_by_id", AsyncMock(return_value=med)):
        await bot.button_callback(update, ctx)

    bot._apply_schedule_times.assert_awaited_once()
    telegram_id, medicine_id, times = bot._apply_schedule_times.await_args.args
    assert telegram_id == 7
    assert medicine_id == 3
    assert times == [time(7, 0), time(15, 0), time(23, 0)]
    assert "editing_schedule_for" not in ctx.user_data

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "כל 8 שעות" in text and "07:00, 15:00, 23:00" in text


@pytest.mark.asyncio
async def test_interval_without_a_selected_medicine_is_reported(bot):
    update, ctx = _update_ctx("time_ivlstart_8_07_00", editing_for=None)
    await bot.button_callback(update, ctx)
    bot._apply_schedule_times.assert_not_awaited()
    assert "אין תרופה נבחרת" in update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_custom_start_time_arms_the_text_prompt(bot):
    update, ctx = _update_ctx("time_ivlcustom_6")
    await bot.button_callback(update, ctx)
    assert ctx.user_data["awaiting_schedule_text"] is True
    assert ctx.user_data["schedule_interval_hours"] == 6


@pytest.mark.asyncio
async def test_plain_custom_time_clears_any_stale_interval(bot):
    """Choosing a one-off custom hour must not inherit an interval from a previous try."""
    update, ctx = _update_ctx("time_custom")
    ctx.user_data["schedule_interval_hours"] = 12
    await bot.button_callback(update, ctx)
    assert "schedule_interval_hours" not in ctx.user_data
    assert ctx.user_data["awaiting_schedule_text"] is True


@pytest.mark.asyncio
async def test_fixed_hour_edit_still_sets_a_single_time(bot):
    """The pre-existing single-hour edit path must keep working."""
    update, ctx = _update_ctx("time_09_30")
    med = MagicMock()
    med.name = "אקמול"
    with patch.object(main.DatabaseManager, "get_medicine_by_id", AsyncMock(return_value=med)):
        await bot.button_callback(update, ctx)

    _, medicine_id, times = bot._apply_schedule_times.await_args.args
    assert medicine_id == 3
    assert times == [time(9, 30)]
