"""Tests for the free-form notes feature (storage + handler flow)."""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.notes_handler import NotesHandler, _preview

# handlers/__init__.py does `from .notes_handler import notes_handler`, which rebinds
# the package attribute from the module to the singleton instance. patch("handlers.
# notes_handler.X") then resolves to the instance on some Python versions and to the
# module on others - it failed only on 3.10. Resolve the module explicitly instead.
notes_module = importlib.import_module("handlers.notes_handler")


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _note(note_id, content, created=None):
    n = MagicMock()
    n.id = note_id
    n.content = content
    n.created_at = created
    return n


@pytest.fixture
def handler():
    return NotesHandler()


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
    return u


async def _arm_edit(handler, ctx, note_id=5, content="קיים"):
    """start_edit_note reads the note to offer it for copying, so it needs the DB."""
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_note(note_id, content))
        await handler.start_edit_note(_callback_update(f"note_edit_{note_id}"), ctx)


# --- preview -------------------------------------------------------------


def test_preview_uses_the_first_line_only():
    assert _preview("שורה ראשונה\nשורה שנייה") == "שורה ראשונה"


def test_preview_truncates_long_notes():
    preview = _preview("א" * 100)
    assert len(preview) <= 40
    assert preview.endswith("…")


def test_preview_survives_an_empty_note():
    assert _preview("") == "(פתק ריק)"
    assert _preview("   \n  ") == "(פתק ריק)"


# --- listing -------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_list_still_offers_adding(handler, ctx):
    update = _callback_update("notes_menu")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_user_notes = AsyncMock(return_value=[])
        await handler.show_notes(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert "note_add" in _callbacks(markup)


@pytest.mark.asyncio
async def test_each_note_gets_its_own_button(handler, ctx):
    update = _callback_update("notes_menu")
    notes = [_note(1, "ראשון"), _note(2, "שני")]
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_user_notes = AsyncMock(return_value=notes)
        await handler.show_notes(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert "note_view_1" in _callbacks(markup)
    assert "note_view_2" in _callbacks(markup)


# --- creating ------------------------------------------------------------


@pytest.mark.asyncio
async def test_adding_a_note_arms_then_saves(handler, ctx):
    await handler.start_add_note(_callback_update("note_add"), ctx)
    assert ctx.user_data["awaiting_note_text"] is True

    update = _text_update("לשאול את הרופא על המינון")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.create_note = AsyncMock()
        db.get_user_notes = AsyncMock(return_value=[])
        claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    db.create_note.assert_awaited_once_with(11, "לשאול את הרופא על המינון")
    assert "awaiting_note_text" not in ctx.user_data


@pytest.mark.asyncio
async def test_unrelated_text_is_not_claimed(handler, ctx):
    """Without a pending note, the message must fall through to the menu routing."""
    claimed = await handler.handle_text(_text_update("שלום"), ctx)
    assert claimed is False


@pytest.mark.asyncio
async def test_an_empty_note_is_rejected(handler, ctx):
    ctx.user_data["awaiting_note_text"] = True
    update = _text_update("    ")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.create_note = AsyncMock()
        claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    db.create_note.assert_not_awaited()
    assert "ריק" in update.message.reply_text.call_args.args[0]


# --- editing and deleting ------------------------------------------------


@pytest.mark.asyncio
async def test_editing_updates_instead_of_creating(handler, ctx):
    await _arm_edit(handler, ctx)
    assert ctx.user_data["editing_note_id"] == 5

    update = _text_update("תוכן מעודכן")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.update_note_for_user = AsyncMock(return_value=True)
        db.create_note = AsyncMock()
        db.get_user_notes = AsyncMock(return_value=[])
        await handler.handle_text(update, ctx)

    # scoped to the owner - see tests/test_notes_reminders_security.py
    db.update_note_for_user.assert_awaited_once_with(5, 11, "תוכן מעודכן")
    db.create_note.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_and_edit_flags_never_coexist(handler, ctx):
    """Starting an edit after an abandoned add must not create a second note."""
    await handler.start_add_note(_callback_update("note_add"), ctx)
    await _arm_edit(handler, ctx)
    assert "awaiting_note_text" not in ctx.user_data
    assert ctx.user_data["editing_note_id"] == 5


@pytest.mark.asyncio
async def test_delete_asks_before_acting(handler, ctx):
    update = _callback_update("note_del_5")
    await handler.ask_delete_note(update, ctx)
    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert set(_callbacks(markup)) == {"notedel_5_confirm", "notedel_5_cancel"}


@pytest.mark.asyncio
async def test_confirming_delete_removes_the_note(handler, ctx):
    update = _callback_update("notedel_5_confirm")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.delete_note_for_user = AsyncMock(return_value=True)
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_user_notes = AsyncMock(return_value=[])
        await handler.confirm_delete_note(update, ctx)

    db.delete_note_for_user.assert_awaited_once_with(5, 11)


@pytest.mark.asyncio
async def test_cancelling_delete_keeps_the_note(handler, ctx):
    update = _callback_update("notedel_5_cancel")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.delete_note_for_user = AsyncMock()
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_note(5, "עדיין כאן"))
        await handler.cancel_delete_note(update, ctx)

    db.delete_note_for_user.assert_not_awaited()
    assert "עדיין כאן" in update.callback_query.edit_message_text.call_args.args[0]


def test_every_button_the_handler_emits_is_registered(handler):
    """A callback with no matching pattern would be silently dead."""
    import re

    patterns = [h.pattern for h in handler.get_handlers()]
    emitted = ["notes_menu", "note_add", "note_view_1", "note_edit_1", "note_del_1",
               "notedel_1_confirm", "notedel_1_cancel"]
    for data in emitted:
        assert any(p.match(data) for p in patterns), f"{data} has no handler"


# --- naming a note -------------------------------------------------------


def _titled(note_id, title, content="גוף הפתק"):
    n = _note(note_id, content)
    n.title = title
    return n


def test_list_label_prefers_the_name_over_the_first_line():
    from handlers.notes_handler import _label

    assert _label(_titled(1, "רופא משפחה", "לשאול על המינון")) == "רופא משפחה"


def test_list_label_falls_back_to_the_first_line_when_unnamed():
    from handlers.notes_handler import _label

    assert _label(_titled(1, None, "לשאול על המינון")) == "לשאול על המינון"
    assert _label(_titled(1, "   ", "לשאול על המינון")) == "לשאול על המינון"


def test_detail_keyboard_offers_naming_and_only_offers_removal_once_named():
    from handlers.notes_handler import _note_detail_keyboard

    unnamed = _callbacks(_note_detail_keyboard(5, has_title=False))
    assert "note_title_5" in unnamed
    assert "note_untitle_5" not in unnamed, "nothing to remove yet"

    named = _callbacks(_note_detail_keyboard(5, has_title=True))
    assert "note_title_5" in named
    assert "note_untitle_5" in named


@pytest.mark.asyncio
async def test_naming_a_note_arms_then_saves(handler, ctx):
    await handler.start_title_note(_callback_update("note_title_5"), ctx)
    assert ctx.user_data["titling_note_id"] == 5

    update = _text_update("רופא משפחה")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.set_note_title_for_user = AsyncMock(return_value=True)
        db.create_note = AsyncMock()
        db.update_note_for_user = AsyncMock()
        db.get_user_notes = AsyncMock(return_value=[])
        claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    db.set_note_title_for_user.assert_awaited_once_with(5, 11, "רופא משפחה")
    db.create_note.assert_not_awaited(), "naming must not create a second note"
    db.update_note_for_user.assert_not_awaited(), "naming must not overwrite the body"
    assert "titling_note_id" not in ctx.user_data


@pytest.mark.asyncio
async def test_an_overlong_name_is_truncated(handler, ctx):
    ctx.user_data["titling_note_id"] = 5
    update = _text_update("א" * 500)
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.set_note_title_for_user = AsyncMock(return_value=True)
        db.get_user_notes = AsyncMock(return_value=[])
        await handler.handle_text(update, ctx)

    assert len(db.set_note_title_for_user.await_args.args[2]) == 100


@pytest.mark.asyncio
async def test_removing_a_name_clears_it(handler, ctx):
    update = _callback_update("note_untitle_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.set_note_title_for_user = AsyncMock(return_value=True)
        db.get_note_for_user = AsyncMock(return_value=_titled(5, None))
        await handler.remove_note_title(update, ctx)

    db.set_note_title_for_user.assert_awaited_once_with(5, 11, None)


@pytest.mark.asyncio
async def test_the_name_is_shown_as_the_heading(handler, ctx):
    update = _callback_update("note_view_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_titled(5, "רופא משפחה", "לשאול על המינון"))
        await handler.view_note(update, ctx)

    body = update.callback_query.edit_message_text.call_args.args[0]
    assert "<b>רופא משפחה</b>" in body


@pytest.mark.asyncio
async def test_a_name_with_markup_is_escaped(handler, ctx):
    """The heading is rendered with parse_mode, so a raw '<' would break it."""
    import html as html_module

    update = _callback_update("note_view_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_titled(5, "<b>שם</b> & עוד"))
        await handler.view_note(update, ctx)

    body = update.callback_query.edit_message_text.call_args.args[0]
    assert html_module.escape("<b>שם</b> & עוד") in body


@pytest.mark.asyncio
async def test_the_three_note_text_flags_never_coexist(handler, ctx):
    """Naming after an abandoned edit must not rewrite the note's body."""
    await _arm_edit(handler, ctx)
    await handler.start_title_note(_callback_update("note_title_5"), ctx)
    assert "editing_note_id" not in ctx.user_data
    assert "awaiting_note_text" not in ctx.user_data
    assert ctx.user_data["titling_note_id"] == 5


def test_the_naming_buttons_are_registered(handler):
    patterns = [h.pattern for h in handler.get_handlers()]
    for data in ("note_title_1", "note_untitle_1"):
        assert any(p.match(data) for p in patterns), f"{data} has no handler"


def test_untitle_is_not_swallowed_by_the_title_pattern(handler):
    """`note_untitle_5` also contains `title`; the patterns must stay distinct."""
    import re

    by_pattern = {h.pattern.pattern: h for h in handler.get_handlers()}
    title_pattern = re.compile(r"^note_title_\d+$")
    assert not title_pattern.match("note_untitle_5")


# --- adding to a note without retyping it --------------------------------


@pytest.mark.asyncio
async def test_appending_adds_a_line_without_touching_the_body(handler, ctx):
    await handler.start_append_note(_callback_update("note_append_5"), ctx)
    assert ctx.user_data["appending_note_id"] == 5

    update = _text_update("גם לשאול על תופעות לוואי")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.append_to_note_for_user = AsyncMock(return_value=True)
        db.update_note_for_user = AsyncMock()
        db.create_note = AsyncMock()
        db.get_user_notes = AsyncMock(return_value=[])
        claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    db.append_to_note_for_user.assert_awaited_once_with(5, 11, "גם לשאול על תופעות לוואי")
    db.update_note_for_user.assert_not_awaited(), "appending must not overwrite the note"
    db.create_note.assert_not_awaited(), "appending must not create a second note"
    assert "appending_note_id" not in ctx.user_data


@pytest.mark.asyncio
async def test_editing_shows_the_current_text_to_copy(handler, ctx):
    """The whole point: the user should not have to retype what is already there."""
    update = _callback_update("note_edit_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_note(5, "השורה הקיימת"))
        await handler.start_edit_note(update, ctx)

    body = update.callback_query.edit_message_text.call_args.args[0]
    # a <code> span is tap-to-copy in Telegram
    assert "<code>השורה הקיימת</code>" in body
    assert update.callback_query.edit_message_text.call_args.kwargs["parse_mode"] == "HTML"
    assert ctx.user_data["editing_note_id"] == 5


@pytest.mark.asyncio
async def test_the_prefilled_body_is_escaped(handler, ctx):
    """Unescaped markup inside <code> would break the message Telegram renders."""
    import html as html_module

    hostile = 'תרופה <b>מודגשת</b> & "ציטוט"'
    update = _callback_update("note_edit_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_note(5, hostile))
        await handler.start_edit_note(update, ctx)

    body = update.callback_query.edit_message_text.call_args.args[0]
    assert html_module.escape(hostile) in body


@pytest.mark.asyncio
async def test_editing_a_foreign_note_shows_nothing_to_copy(handler, ctx):
    """The prefill is a read, so it needs the same ownership scoping as the rest."""
    update = _callback_update("note_edit_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=None)
        await handler.start_edit_note(update, ctx)

    assert "לא נמצא" in update.callback_query.edit_message_text.call_args.args[0]
    assert "editing_note_id" not in ctx.user_data, "a failed prefill must not arm the edit"


@pytest.mark.asyncio
async def test_the_edit_screen_offers_appending_instead(handler, ctx):
    update = _callback_update("note_edit_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=_user())
        db.get_note_for_user = AsyncMock(return_value=_note(5, "קיים"))
        await handler.start_edit_note(update, ctx)

    markup = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
    assert "note_append_5" in _callbacks(markup)


@pytest.mark.asyncio
async def test_all_four_note_text_flags_stay_exclusive(handler, ctx):
    await handler.start_append_note(_callback_update("note_append_5"), ctx)
    await handler.start_title_note(_callback_update("note_title_5"), ctx)
    assert "appending_note_id" not in ctx.user_data
    assert ctx.user_data["titling_note_id"] == 5


def test_the_note_card_offers_adding(handler):
    from handlers.notes_handler import _note_detail_keyboard

    assert "note_append_5" in _callbacks(_note_detail_keyboard(5))


def test_the_append_button_is_registered(handler):
    patterns = [h.pattern for h in handler.get_handlers()]
    assert any(p.match("note_append_1") for p in patterns)


# --- menu wiring -------------------------------------------------------------


def test_the_pharmacy_button_is_gone_from_the_menu():
    """Clalit's WAF blocks the search API from the host, so the button could
    only ever report its own failure."""
    import importlib

    keyboards = importlib.import_module("utils.keyboards")
    labels = [
        button.text
        for row in keyboards.get_main_menu_keyboard().keyboard
        for button in row
    ]
    assert not any("מלאי בית מרקחת" in label for label in labels)
    assert any("חירום" in label for label in labels), "the emergency button went with it"


def test_the_removed_button_no_longer_routes():
    import importlib

    main = importlib.import_module("main")
    assert "🏥 מלאי בית מרקחת" not in main.MAIN_MENU_ACTIONS


def test_help_describes_the_emergency_guide():
    from config import config

    assert "חירום" in config.HELP_MESSAGE
    assert "מרחב המוגן" in config.HELP_MESSAGE


# --- a retired button is still navigation ------------------------------------
#
# Telegram keeps a reply keyboard on the client until it is replaced, so the
# pharmacy button lives on for anyone who has not reopened the bot since it was
# removed. If that tap stopped counting as navigation, it would be saved as
# whatever the user happened to be drafting.


def test_the_retired_label_is_still_recognised_as_navigation():
    import importlib

    main = importlib.import_module("main")
    assert "🏥 מלאי בית מרקחת" in main.RETIRED_MENU_LABELS
    assert "🏥 מלאי בית מרקחת" not in main.MAIN_MENU_ACTIONS, "it must not route anywhere"


def test_no_retired_label_is_also_a_live_one():
    """A label in both sets would answer 'this was removed' for a working feature."""
    import importlib

    main = importlib.import_module("main")
    assert not (main.RETIRED_MENU_LABELS & set(main.MAIN_MENU_ACTIONS))


def test_every_retired_label_is_off_the_keyboard():
    import importlib

    main = importlib.import_module("main")
    keyboards = importlib.import_module("utils.keyboards")
    live = {
        button.text
        for row in keyboards.get_main_menu_keyboard().keyboard
        for button in row
    }
    assert not (main.RETIRED_MENU_LABELS & live), "a retired label is still on the menu"


# --- a retired label, end to end ---------------------------------------------


def _bot_and_update(label="🏥 מלאי בית מרקחת"):
    import importlib
    from unittest.mock import AsyncMock, MagicMock

    main = importlib.import_module("main")
    bot = main.MedicineReminderBot.__new__(main.MedicineReminderBot)

    update = MagicMock()
    update.message.text = label
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    return main, bot, update, context


@pytest.mark.asyncio
async def test_a_retired_label_is_answered_and_never_saved_as_a_draft():
    """The regression: mid-note, the stale button became the note's text."""
    from unittest.mock import AsyncMock, patch

    main, bot, update, context = _bot_and_update()
    context.user_data.update({"awaiting_note_text": True, "custom_reminder_draft": {"text": "x"}})

    from handlers import notes_handler

    with patch.object(notes_handler, "handle_text", AsyncMock(return_value=True)) as notes:
        await bot.handle_text_message(update, context)

    assert not notes.await_count, "the label reached the notes handler"
    assert "awaiting_note_text" not in context.user_data
    assert "custom_reminder_draft" not in context.user_data
    assert update.message.reply_text.await_args.args[0] == main.RETIRED_MENU_REPLY


@pytest.mark.asyncio
async def test_a_retired_label_beats_an_open_appointment_flow():
    """appt_state routes before everything else, so the check has to precede it."""
    from unittest.mock import AsyncMock, patch

    _main, bot, update, context = _bot_and_update()
    context.user_data["appt_state"] = "awaiting_title"

    import main as main_module

    with patch.object(main_module.appointments_handler, "handle_text", AsyncMock()) as appts:
        await bot.handle_text_message(update, context)

    assert not appts.await_count, "the label was taken as the appointment title"
    assert "appt_state" not in context.user_data


@pytest.mark.asyncio
async def test_a_retired_label_clears_edit_state_too():
    """Otherwise the next message is read as input for a flow the user left."""
    _main, bot, update, context = _bot_and_update()
    context.user_data.update({"updating_inventory_for": 3, "editing_field_for": {"id": 1}})

    await bot.handle_text_message(update, context)

    assert "updating_inventory_for" not in context.user_data
    assert "editing_field_for" not in context.user_data


@pytest.mark.asyncio
async def test_a_live_menu_label_is_not_handed_to_the_draft_handlers():
    """The original code skipped them for menu labels; that must stay true."""
    from unittest.mock import AsyncMock, patch

    _main, bot, update, context = _bot_and_update(label="📝 פתקים")
    context.user_data["awaiting_note_text"] = True

    from handlers import notes_handler

    with patch.object(notes_handler, "handle_text", AsyncMock(return_value=True)) as notes:
        await bot.handle_text_message(update, context)

    assert not notes.await_count
