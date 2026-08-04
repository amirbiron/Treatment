"""Routing tests for the every-X-hours option in the add-medicine conversation.

The interval callbacks all share the ``time_`` prefix so the existing
conversation state routes them, which means the dispatch order inside
handle_time_selection is what keeps ``time_ivl_back`` from being parsed as an
interval and ``time_ivlstart_8_07_00`` from being parsed as a clock time.
"""

import re
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers.medicine_handler import (
    CUSTOM_TIME_INPUT,
    MEDICINE_SCHEDULE,
    MedicineHandler,
)
from telegram.ext import ConversationHandler
from utils.keyboards import (
    get_interval_selection_keyboard,
    get_interval_start_keyboard,
    get_time_selection_keyboard,
)
from utils.schedule import INTERVAL_HOURS_CHOICES


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.fixture
def handler():
    h = MedicineHandler()
    h._create_medicine_in_db = AsyncMock(return_value=True)
    h.user_medicine_data[7] = {"step": "schedule", "medicine_data": {"name": "אקמול", "dosage": "500 מ\"ג"}}
    return h


def _update(data):
    update = MagicMock()
    update.effective_user.id = 7
    update.callback_query = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _ctx():
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def test_interval_button_only_offered_where_it_makes_sense():
    """Appointments reuse this keyboard, and a repeating interval is meaningless there."""
    assert "time_interval" not in _callbacks(get_time_selection_keyboard())
    assert "time_interval" in _callbacks(get_time_selection_keyboard(include_interval=True))


def test_every_new_callback_is_routed_by_the_conversation_state():
    """All interval callbacks must match the state's ^time_ pattern to be delivered."""
    pattern = re.compile("^time_")
    produced = set(_callbacks(get_time_selection_keyboard(include_interval=True)))
    produced |= set(_callbacks(get_interval_selection_keyboard()))
    for hours in INTERVAL_HOURS_CHOICES:
        produced |= set(_callbacks(get_interval_start_keyboard(hours)))

    unrouted = [c for c in produced if not pattern.match(c)]
    assert not unrouted, f"these buttons would be silently dropped: {unrouted}"


@pytest.mark.asyncio
async def test_interval_entry_shows_the_interval_choices(handler):
    update = _update("time_interval")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == MEDICINE_SCHEDULE
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    offered = [c for c in _callbacks(markup) if c.startswith("time_ivl_") and c != "time_ivl_back"]
    assert offered == [f"time_ivl_{h}" for h in INTERVAL_HOURS_CHOICES]


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", INTERVAL_HOURS_CHOICES)
async def test_picking_an_interval_asks_for_a_start_time(handler, hours):
    update = _update(f"time_ivl_{hours}")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == MEDICINE_SCHEDULE
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    starts = [c for c in _callbacks(markup) if c.startswith("time_ivlstart_")]
    assert starts, "no start-time buttons offered"
    assert all(c.startswith(f"time_ivlstart_{hours}_") for c in starts)


@pytest.mark.asyncio
async def test_back_is_not_mistaken_for_an_interval(handler):
    """`time_ivl_back` reaches the same prefix as `time_ivl_<hours>`; order decides."""
    update = _update("time_ivl_back")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == MEDICINE_SCHEDULE
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert "time_interval" in _callbacks(markup), "should return to the time keyboard"


@pytest.mark.asyncio
async def test_start_time_creates_the_medicine_with_every_expanded_time(handler):
    update = _update("time_ivlstart_8_07_00")
    state = await handler.handle_time_selection(update, _ctx())

    assert state == ConversationHandler.END
    handler._create_medicine_in_db.assert_awaited_once()
    # user_medicine_data is cleared on success, so inspect what was saved
    saved = handler._create_medicine_in_db.await_args.args[0]
    assert saved == 7

    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "כל 8 שעות" in text
    assert "07:00, 15:00, 23:00" in text


@pytest.mark.asyncio
async def test_start_time_is_not_parsed_as_a_clock_time(handler):
    """`time_ivlstart_12_09_00` must not be read as hour=ivlstart."""
    update = _update("time_ivlstart_12_09_00")
    await handler.handle_time_selection(update, _ctx())
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "כל 12 שעות" in text
    assert "09:00, 21:00" in text


@pytest.mark.asyncio
async def test_custom_start_time_waits_for_text_input(handler):
    update = _update("time_ivlcustom_6")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == CUSTOM_TIME_INPUT
    assert handler.user_medicine_data[7]["medicine_data"]["interval_hours"] == 6


@pytest.mark.asyncio
async def test_typed_start_time_expands_the_interval(handler):
    await handler.handle_time_selection(_update("time_ivlcustom_6"), _ctx())

    update = MagicMock()
    update.effective_user.id = 7
    update.callback_query = None
    update.message.text = "06:30"
    update.message.reply_text = AsyncMock()

    state = await handler.get_custom_time(update, _ctx())
    assert state == ConversationHandler.END
    text = update.message.reply_text.call_args.args[0]
    assert "כל 6 שעות" in text
    assert "00:30, 06:30, 12:30, 18:30" in text


@pytest.mark.asyncio
async def test_plain_time_button_still_creates_a_single_reminder(handler):
    """The pre-existing fixed-hour path must be untouched."""
    update = _update("time_08_00")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == ConversationHandler.END
    text = update.callback_query.edit_message_text.call_args.args[0]
    assert "08:00" in text
    assert "כל" not in text.split("שעות נטילה")[0].replace("שעות נטילה", "")


@pytest.mark.asyncio
async def test_typed_time_without_interval_still_creates_a_single_reminder(handler):
    update = MagicMock()
    update.effective_user.id = 7
    update.callback_query = None
    update.message.text = "21:45"
    update.message.reply_text = AsyncMock()

    state = await handler.get_custom_time(update, _ctx())
    assert state == ConversationHandler.END
    text = update.message.reply_text.call_args.args[0]
    assert "21:45" in text
    assert "🔁" not in text


@pytest.mark.asyncio
async def test_unsupported_interval_button_is_reported(handler):
    """A stale button must produce a specific message, not a generic error."""
    update = _update("time_ivl_5")
    state = await handler.handle_time_selection(update, _ctx())
    assert state == MEDICINE_SCHEDULE
    handler._create_medicine_in_db.assert_not_awaited()
    assert "אינו נתמך" in update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_plain_custom_time_clears_any_stale_interval(handler):
    """Interval -> back -> plain custom hour must not inherit the interval."""
    await handler.handle_time_selection(_update("time_ivlcustom_6"), _ctx())
    await handler.handle_time_selection(_update("time_ivl_back"), _ctx())
    await handler.handle_time_selection(_update("time_custom"), _ctx())
    assert "interval_hours" not in handler.user_medicine_data[7]["medicine_data"]

    update = MagicMock()
    update.effective_user.id = 7
    update.callback_query = None
    update.message.text = "08:00"
    update.message.reply_text = AsyncMock()
    await handler.get_custom_time(update, _ctx())

    text = update.message.reply_text.call_args.args[0]
    assert "08:00" in text and "🔁" not in text


@pytest.mark.asyncio
async def test_a_stale_unsupported_interval_is_reported_not_crashed(handler):
    handler.user_medicine_data[7]["medicine_data"]["interval_hours"] = 5
    update = MagicMock()
    update.effective_user.id = 7
    update.callback_query = None
    update.message.text = "08:00"
    update.message.reply_text = AsyncMock()

    state = await handler.get_custom_time(update, _ctx())
    assert state == MEDICINE_SCHEDULE
    handler._create_medicine_in_db.assert_not_awaited()
    assert "אינו נתמך" in update.message.reply_text.call_args.args[0]
