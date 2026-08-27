"""Ownership and escaping regressions for notes and standalone reminders.

Callback data reaches the bot from the client, so a record id in a button is not
proof that the record belongs to whoever pressed it. Every handler path that
reads or mutates by id must go through an owner-scoped query.

Separately, free-form user text is rendered with parse_mode set. Unescaped
markup does not merely look wrong - Telegram rejects the whole message, so a
note becomes unreadable and a scheduled reminder is never delivered.
"""

import html
import importlib
from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

notes_module = importlib.import_module("handlers.notes_handler")


@pytest.fixture(autouse=True)
def not_muted():
    """Delivery checks the user's mute setting before composing anything.

    The helper resolves DatabaseManager through its own import, so patching the
    name in the scheduler's namespace does not reach it - without this, these
    tests would open a real database session. Muting is covered in
    test_quiet_mode.py; these tests are about ownership and escaping.
    """
    with patch(
        "database.DatabaseManager.get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=False)),
    ):
        yield
reminder_module = importlib.import_module("handlers.custom_reminder_handler")

from handlers.custom_reminder_handler import CustomReminderHandler  # noqa: E402
from handlers.notes_handler import NotesHandler  # noqa: E402

HOSTILE = 'תרופה <b>מודגשת</b> & "ציטוט" *כוכבית* _קו_'


# --- storage: a foreign id must miss --------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import database as database_module

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sec.db", future=True)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "async_session", async_sessionmaker(engine, expire_on_commit=False))
    async with engine.begin() as conn:
        await conn.run_sync(database_module.Base.metadata.create_all)
    yield database_module
    await engine.dispose()


@pytest_asyncio.fixture
async def two_users(db):
    DB = db.DatabaseManager
    owner = await DB.create_user(telegram_id=1, username="owner", first_name="O")
    other = await DB.create_user(telegram_id=2, username="other", first_name="X")
    return DB, owner, other


@pytest.mark.asyncio
async def test_another_user_cannot_read_a_note(two_users):
    DB, owner, other = two_users
    note = await DB.create_note(owner.id, "פרטי")

    assert (await DB.get_note_for_user(note.id, owner.id)).content == "פרטי"
    assert await DB.get_note_for_user(note.id, other.id) is None


@pytest.mark.asyncio
async def test_another_user_cannot_edit_a_note(two_users):
    DB, owner, other = two_users
    note = await DB.create_note(owner.id, "מקורי")

    assert await DB.update_note_for_user(note.id, other.id, "נחטף") is False
    assert (await DB.get_note_by_id(note.id)).content == "מקורי"


@pytest.mark.asyncio
async def test_another_user_cannot_delete_a_note(two_users):
    DB, owner, other = two_users
    note = await DB.create_note(owner.id, "שלי")

    assert await DB.delete_note_for_user(note.id, other.id) is False
    assert await DB.get_note_by_id(note.id) is not None

    assert await DB.delete_note_for_user(note.id, owner.id) is True
    assert await DB.get_note_by_id(note.id) is None


@pytest.mark.asyncio
async def test_another_user_cannot_read_or_delete_a_reminder(two_users):
    DB, owner, other = two_users
    reminder = await DB.create_custom_reminder(owner.id, "פרטי", "daily", remind_time=time(8, 0))

    assert await DB.get_custom_reminder_for_user(reminder.id, other.id) is None
    assert await DB.delete_custom_reminder_for_user(reminder.id, other.id) is False
    assert await DB.get_custom_reminder_by_id(reminder.id) is not None

    assert await DB.get_custom_reminder_for_user(reminder.id, owner.id) is not None
    assert await DB.delete_custom_reminder_for_user(reminder.id, owner.id) is True


# --- handlers: a forged callback id must not act --------------------------


def _query(data, telegram_id=2):
    q = MagicMock()
    q.data = data
    q.from_user.id = telegram_id
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


def _callback_update(data, telegram_id=2):
    u = MagicMock()
    u.effective_user.id = telegram_id
    u.callback_query = _query(data, telegram_id)
    return u


def _ctx():
    c = MagicMock()
    c.user_data = {}
    return c


@pytest.mark.asyncio
async def test_viewing_a_foreign_note_reports_not_found():
    handler = NotesHandler()
    update = _callback_update("note_view_5")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.get_note_for_user = AsyncMock(return_value=None)  # not theirs
        await handler.view_note(update, _ctx())

    db.get_note_for_user.assert_awaited_once_with(5, 99)
    assert "לא נמצא" in update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_deleting_a_note_goes_through_the_scoped_query():
    handler = NotesHandler()
    update = _callback_update("notedel_5_confirm")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.delete_note_for_user = AsyncMock(return_value=False)
        db.delete_note = AsyncMock()
        db.get_user_notes = AsyncMock(return_value=[])
        await handler.confirm_delete_note(update, _ctx())

    db.delete_note_for_user.assert_awaited_once_with(5, 99)
    db.delete_note.assert_not_awaited(), "the unscoped delete must not be reachable from a callback"


@pytest.mark.asyncio
async def test_editing_a_foreign_note_changes_nothing():
    handler = NotesHandler()
    ctx = _ctx()
    ctx.user_data["editing_note_id"] = 5

    update = MagicMock()
    update.effective_user.id = 2
    update.callback_query = None
    update.message.text = "נחטף"
    update.message.reply_text = AsyncMock()

    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.update_note_for_user = AsyncMock(return_value=False)  # not theirs
        db.create_note = AsyncMock()
        await handler.handle_text(update, ctx)

    db.update_note_for_user.assert_awaited_once_with(5, 99, "נחטף")
    db.create_note.assert_not_awaited(), "a failed edit must not fall back to creating"
    assert "לא נמצא" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_note_text_from_an_unknown_user_is_refused():
    """A user with no database row must not reach create_note."""
    handler = NotesHandler()
    ctx = _ctx()
    ctx.user_data["awaiting_note_text"] = True

    update = MagicMock()
    update.effective_user.id = 2
    update.callback_query = None
    update.message.text = "פתק"
    update.message.reply_text = AsyncMock()

    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=None)
        db.create_note = AsyncMock()
        claimed = await handler.handle_text(update, ctx)

    assert claimed is True
    db.create_note.assert_not_awaited()
    from config import config

    assert update.message.reply_text.call_args.args[0] == config.ERROR_MESSAGES["unauthorized"]


@pytest.mark.asyncio
async def test_deleting_a_foreign_reminder_neither_cancels_nor_deletes():
    handler = CustomReminderHandler()
    update = _callback_update("cremdel_9_confirm")
    with patch.object(reminder_module, "DatabaseManager") as db, patch.object(
        reminder_module, "medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.get_custom_reminder_for_user = AsyncMock(return_value=None)  # not theirs
        db.delete_custom_reminder_for_user = AsyncMock()
        db.delete_custom_reminder = AsyncMock()
        db.get_user_custom_reminders = AsyncMock(return_value=[])
        sched.cancel_custom_reminder = AsyncMock()
        await handler.confirm_delete(update, _ctx())

    db.delete_custom_reminder_for_user.assert_not_awaited()
    db.delete_custom_reminder.assert_not_awaited()
    sched.cancel_custom_reminder.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_prompt_for_a_foreign_reminder_falls_back_to_the_list():
    handler = CustomReminderHandler()
    update = _callback_update("crem_del_9")
    with patch.object(reminder_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.get_custom_reminder_for_user = AsyncMock(return_value=None)
        db.get_user_custom_reminders = AsyncMock(return_value=[])
        await handler.ask_delete(update, _ctx())

    db.get_custom_reminder_for_user.assert_awaited_once_with(9, 99)
    # falls through to show_menu rather than rendering someone else's reminder
    assert "תזכורות אישיות" in update.callback_query.edit_message_text.call_args.args[0]


# --- escaping -------------------------------------------------------------


@pytest.mark.asyncio
async def test_note_content_is_escaped_when_rendered():
    handler = NotesHandler()
    note = MagicMock()
    note.id = 1
    note.content = HOSTILE
    note.created_at = datetime(2026, 8, 5, 10, 0)

    update = _callback_update("note_view_1")
    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.get_note_for_user = AsyncMock(return_value=note)
        await handler.view_note(update, _ctx())

    call = update.callback_query.edit_message_text.call_args
    assert call.kwargs["parse_mode"] == "HTML"
    assert html.escape(HOSTILE) in call.args[0]
    assert "<b>מודגשת</b>" not in call.args[0], "user markup leaked into the message"


@pytest.mark.asyncio
async def test_reminder_text_is_escaped_in_the_creation_prompt():
    handler = CustomReminderHandler()
    ctx = _ctx()
    ctx.user_data["awaiting_custom_reminder_text"] = True

    update = MagicMock()
    update.effective_user.id = 2
    update.callback_query = None
    update.message.text = HOSTILE
    update.message.reply_text = AsyncMock()

    await handler.handle_text(update, ctx)

    body = update.message.reply_text.call_args.args[0]
    assert html.escape(HOSTILE) in body
    # the raw text is still what gets stored
    assert ctx.user_data["custom_reminder_draft"]["text"] == HOSTILE


@pytest.mark.asyncio
async def test_delivered_reminder_is_escaped_so_it_actually_sends():
    """An unescaped '*' makes Telegram reject the message and the reminder is lost."""
    from scheduler import MedicineScheduler

    sched = MedicineScheduler()
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()

    reminder = MagicMock()
    reminder.text = HOSTILE
    reminder.repeat = "daily"
    reminder.is_active = True
    user = MagicMock()
    user.telegram_id = 7
    user.is_active = True

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=reminder)
        db.get_user_by_id = AsyncMock(return_value=user)
        await sched._send_custom_reminder(11, 1)

    kwargs = sched.bot.send_message.call_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert html.escape(HOSTILE) in kwargs["text"]
    assert "<b>מודגשת</b>" not in kwargs["text"]


# --- failure paths --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_schedule_does_not_leave_an_orphan_reminder():
    """The row is committed before scheduling; if arming raises it must be undone."""
    handler = CustomReminderHandler()
    ctx = _ctx()
    ctx.user_data["custom_reminder_draft"] = {"text": "בדיקה", "repeat": "daily"}
    update = _callback_update("crem_time_08_00")

    saved = MagicMock()
    saved.id = 9
    saved.text = "בדיקה"
    with patch.object(reminder_module, "DatabaseManager") as db, patch.object(
        reminder_module, "medicine_scheduler"
    ) as sched:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.create_custom_reminder = AsyncMock(return_value=saved)
        db.delete_custom_reminder_for_user = AsyncMock()
        sched.schedule_custom_reminder = AsyncMock(side_effect=RuntimeError("scheduler down"))
        await handler.pick_time(update, ctx)

    db.delete_custom_reminder_for_user.assert_awaited_once_with(9, 99)
    # the draft survives so the user can simply press the time again
    assert ctx.user_data["custom_reminder_draft"]["text"] == "בדיקה"


@pytest.mark.asyncio
async def test_a_one_off_that_fails_to_send_is_retired():
    """Its DateTrigger already fired, so an active row would be stranded forever."""
    from scheduler import MedicineScheduler

    sched = MedicineScheduler()
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))

    reminder = MagicMock()
    reminder.text = "פעם אחת"
    reminder.repeat = "once"
    reminder.is_active = True
    user = MagicMock()
    user.telegram_id = 7
    user.is_active = True

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=reminder)
        db.get_user_by_id = AsyncMock(return_value=user)
        db.set_custom_reminder_active = AsyncMock()
        await sched._send_custom_reminder(11, 1)

    db.set_custom_reminder_active.assert_awaited_once_with(1, False)


@pytest.mark.asyncio
async def test_a_repeating_reminder_that_fails_to_send_stays_active():
    """It will fire again on its cron schedule, so retiring it would lose it."""
    from scheduler import MedicineScheduler

    sched = MedicineScheduler()
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))

    reminder = MagicMock()
    reminder.text = "כל יום"
    reminder.repeat = "daily"
    reminder.is_active = True

    with patch("scheduler.DatabaseManager") as db:
        db.get_custom_reminder_by_id = AsyncMock(return_value=reminder)
        db.get_user_by_id = AsyncMock(return_value=MagicMock(telegram_id=7, is_active=True))
        db.set_custom_reminder_active = AsyncMock()
        await sched._send_custom_reminder(11, 1)

    db.set_custom_reminder_active.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_menu_press_navigates_instead_of_becoming_note_content():
    """"📝 פתקים" typed while editing a note must not overwrite the note with it."""
    import main

    bot = main.MedicineReminderBot.__new__(main.MedicineReminderBot)
    ctx = _ctx()
    ctx.user_data["editing_note_id"] = 5

    update = MagicMock()
    update.effective_user.id = 2
    update.callback_query = None
    update.message.text = "📝 פתקים"
    update.message.reply_text = AsyncMock()

    with patch.object(notes_module, "DatabaseManager") as db:
        db.get_user_by_telegram_id = AsyncMock(return_value=MagicMock(id=99))
        db.get_user_notes = AsyncMock(return_value=[])
        db.update_note_for_user = AsyncMock()
        db.create_note = AsyncMock()
        await bot.handle_text_message(update, ctx)

    db.update_note_for_user.assert_not_awaited(), "the menu label was saved as note content"
    db.create_note.assert_not_awaited()
    assert "editing_note_id" not in ctx.user_data
    assert "הפתקים שלי" in update.message.reply_text.call_args.args[0]
