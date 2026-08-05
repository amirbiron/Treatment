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
    await handler.start_edit_note(_callback_update("note_edit_5"), ctx)
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
    await handler.start_edit_note(_callback_update("note_edit_5"), ctx)
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
