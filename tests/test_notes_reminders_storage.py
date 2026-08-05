"""Storage round-trips for notes and standalone reminders on the SQL backend.

The Mongo manager is checked for surface parity only - it needs a live server -
but a method missing there would break the bot at runtime with DB_BACKEND=mongo,
which is what production uses.
"""

from datetime import datetime, time

import pytest
import pytest_asyncio

NEW_METHODS = [
    "create_note",
    "get_user_notes",
    "get_note_by_id",
    "update_note",
    "set_note_title_for_user",
    "append_to_note_for_user",
    "delete_note",
    "create_custom_reminder",
    "get_user_custom_reminders",
    "get_custom_reminder_by_id",
    "set_custom_reminder_active",
    "delete_custom_reminder",
    "get_all_active_custom_reminders",
]


def test_both_backends_expose_the_same_methods():
    import database
    from database import DatabaseManagerMongo

    sql_manager = database.DatabaseManager
    for name in NEW_METHODS:
        assert hasattr(sql_manager, name), f"SQL backend missing {name}"
        assert hasattr(DatabaseManagerMongo, name), f"Mongo backend missing {name}"


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """A throwaway sqlite database with the schema created.

    The engine is swapped in place rather than reloading the module: other test
    modules already hold references to this DatabaseManager, and reloading would
    hand them a different class object.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import database as database_module

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "async_session", session_factory)

    async with engine.begin() as conn:
        await conn.run_sync(database_module.Base.metadata.create_all)

    yield database_module
    await engine.dispose()


@pytest.mark.asyncio
async def test_notes_round_trip(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=999, username="t", first_name="T")

    first = await DB.create_note(user.id, "לשאול את הרופא על המינון")
    second = await DB.create_note(user.id, "אקמול נגמר בשבוע הבא")

    notes = await DB.get_user_notes(user.id)
    assert [n.id for n in notes] == [second.id, first.id], "newest first"

    assert await DB.update_note(first.id, "עודכן")
    assert (await DB.get_note_by_id(first.id)).content == "עודכן"

    assert await DB.delete_note(first.id)
    assert [n.id for n in await DB.get_user_notes(user.id)] == [second.id]


@pytest.mark.asyncio
async def test_missing_note_reports_rather_than_raising(db):
    DB = db.DatabaseManager
    assert await DB.get_note_by_id(4242) is None
    assert await DB.delete_note(4242) is False
    assert await DB.update_note(4242, "x") is False


@pytest.mark.asyncio
async def test_custom_reminders_round_trip(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=998, username="t", first_name="T")

    once = await DB.create_custom_reminder(
        user.id, "לקחת מרשם", "once", remind_at=datetime(2030, 9, 1, 10, 0)
    )
    daily = await DB.create_custom_reminder(user.id, "למדוד לחץ דם", "daily", remind_time=time(8, 0))
    weekly = await DB.create_custom_reminder(user.id, "שקילה", "weekly", remind_time=time(7, 30), weekday=6)

    stored = {r.id: r for r in await DB.get_user_custom_reminders(user.id)}
    assert len(stored) == 3
    assert stored[once.id].remind_at == datetime(2030, 9, 1, 10, 0)
    assert stored[once.id].remind_time is None
    assert stored[daily.id].remind_time == time(8, 0)
    assert stored[weekly.id].weekday == 6


@pytest.mark.asyncio
async def test_deactivating_hides_a_reminder_without_losing_it(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=997, username="t", first_name="T")
    reminder = await DB.create_custom_reminder(user.id, "פעם אחת", "once", remind_at=datetime(2030, 1, 1))

    assert await DB.set_custom_reminder_active(reminder.id, False)
    assert await DB.get_user_custom_reminders(user.id) == []
    assert len(await DB.get_user_custom_reminders(user.id, active_only=False)) == 1
    assert await DB.get_custom_reminder_by_id(reminder.id) is not None


@pytest.mark.asyncio
async def test_only_active_reminders_are_rearmed_on_restart(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=996, username="t", first_name="T")
    live = await DB.create_custom_reminder(user.id, "חי", "daily", remind_time=time(8, 0))
    spent = await DB.create_custom_reminder(user.id, "כבוי", "daily", remind_time=time(9, 0))
    await DB.set_custom_reminder_active(spent.id, False)

    assert [r.id for r in await DB.get_all_active_custom_reminders()] == [live.id]


@pytest.mark.asyncio
async def test_notes_are_scoped_to_their_owner(db):
    DB = db.DatabaseManager
    mine = await DB.create_user(telegram_id=1, username="a", first_name="A")
    theirs = await DB.create_user(telegram_id=2, username="b", first_name="B")
    await DB.create_note(mine.id, "שלי")
    await DB.create_note(theirs.id, "שלהם")

    assert [n.content for n in await DB.get_user_notes(mine.id)] == ["שלי"]
    assert [n.content for n in await DB.get_user_notes(theirs.id)] == ["שלהם"]


@pytest.mark.asyncio
async def test_reminders_are_scoped_to_their_owner(db):
    DB = db.DatabaseManager
    mine = await DB.create_user(telegram_id=3, username="a", first_name="A")
    theirs = await DB.create_user(telegram_id=4, username="b", first_name="B")
    await DB.create_custom_reminder(mine.id, "שלי", "daily", remind_time=time(8, 0))
    await DB.create_custom_reminder(theirs.id, "שלהם", "daily", remind_time=time(9, 0))

    assert [r.text for r in await DB.get_user_custom_reminders(mine.id)] == ["שלי"]
    assert [r.text for r in await DB.get_user_custom_reminders(theirs.id)] == ["שלהם"]


@pytest.mark.asyncio
async def test_a_note_can_be_named_renamed_and_unnamed(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=995, username="t", first_name="T")

    plain = await DB.create_note(user.id, "בלי שם")
    assert plain.title is None, "naming stays optional"

    named = await DB.create_note(user.id, "עם שם", title="רופא משפחה")
    assert (await DB.get_note_by_id(named.id)).title == "רופא משפחה"

    assert await DB.set_note_title_for_user(plain.id, user.id, "שם חדש")
    assert (await DB.get_note_by_id(plain.id)).title == "שם חדש"

    # an empty title clears rather than storing ""
    assert await DB.set_note_title_for_user(plain.id, user.id, "")
    assert (await DB.get_note_by_id(plain.id)).title is None


@pytest.mark.asyncio
async def test_renaming_leaves_the_body_alone(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=994, username="t", first_name="T")
    note = await DB.create_note(user.id, "הגוף המקורי")

    await DB.set_note_title_for_user(note.id, user.id, "כותרת")
    stored = await DB.get_note_by_id(note.id)
    assert stored.content == "הגוף המקורי"
    assert stored.title == "כותרת"


@pytest.mark.asyncio
async def test_editing_the_body_leaves_the_name_alone(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=993, username="t", first_name="T")
    note = await DB.create_note(user.id, "גוף", title="כותרת")

    await DB.update_note_for_user(note.id, user.id, "גוף חדש")
    stored = await DB.get_note_by_id(note.id)
    assert stored.title == "כותרת", "editing the body dropped the name"
    assert stored.content == "גוף חדש"


@pytest.mark.asyncio
async def test_another_user_cannot_rename_a_note(db):
    DB = db.DatabaseManager
    owner = await DB.create_user(telegram_id=992, username="a", first_name="A")
    other = await DB.create_user(telegram_id=991, username="b", first_name="B")
    note = await DB.create_note(owner.id, "שלי", title="שלי")

    assert await DB.set_note_title_for_user(note.id, other.id, "נחטף") is False
    assert (await DB.get_note_by_id(note.id)).title == "שלי"


# --- title normalization -------------------------------------------------


def test_the_title_limit_has_one_source():
    """The column width, the migration and the handler must not drift apart."""
    import importlib

    import database

    handler_module = importlib.import_module("handlers.notes_handler")
    assert handler_module.MAX_TITLE_LENGTH == database.MAX_NOTE_TITLE_LENGTH

    column = database.Note.__table__.columns["title"]
    assert column.type.length == database.MAX_NOTE_TITLE_LENGTH


def test_blank_titles_normalize_to_none():
    """'Unnamed' must have exactly one representation in the database."""
    from database import MAX_NOTE_TITLE_LENGTH, normalize_note_title

    assert normalize_note_title(None) is None
    assert normalize_note_title("") is None
    assert normalize_note_title("   ") is None
    assert normalize_note_title("\n\t ") is None
    assert normalize_note_title("  רופא משפחה  ") == "רופא משפחה"
    assert len(normalize_note_title("א" * 500)) == MAX_NOTE_TITLE_LENGTH


@pytest.mark.asyncio
async def test_creating_with_a_blank_title_stores_none(db):
    """create_note and the setter must agree on what unnamed looks like."""
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=990, username="t", first_name="T")

    for blank in ("", "   ", None):
        note = await DB.create_note(user.id, "גוף", title=blank)
        assert (await DB.get_note_by_id(note.id)).title is None, f"{blank!r} was stored verbatim"


@pytest.mark.asyncio
async def test_titles_are_trimmed_and_capped_on_both_paths(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=989, username="t", first_name="T")

    created = await DB.create_note(user.id, "גוף", title="  עם רווחים  ")
    assert (await DB.get_note_by_id(created.id)).title == "עם רווחים"

    await DB.set_note_title_for_user(created.id, user.id, "  אחרי שינוי  ")
    assert (await DB.get_note_by_id(created.id)).title == "אחרי שינוי"

    await DB.set_note_title_for_user(created.id, user.id, "א" * 500)
    assert len((await DB.get_note_by_id(created.id)).title) == db.MAX_NOTE_TITLE_LENGTH


# --- appending -----------------------------------------------------------


@pytest.mark.asyncio
async def test_appending_keeps_what_was_already_written(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=988, username="t", first_name="T")
    note = await DB.create_note(user.id, "לשאול על המינון")

    assert await DB.append_to_note_for_user(note.id, user.id, "וגם על תופעות לוואי")
    assert (await DB.get_note_by_id(note.id)).content == "לשאול על המינון\nוגם על תופעות לוואי"

    await DB.append_to_note_for_user(note.id, user.id, "ועל שעות הנטילה")
    assert (await DB.get_note_by_id(note.id)).content.splitlines() == [
        "לשאול על המינון",
        "וגם על תופעות לוואי",
        "ועל שעות הנטילה",
    ]


@pytest.mark.asyncio
async def test_appending_does_not_pile_up_blank_lines(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=987, username="t", first_name="T")
    note = await DB.create_note(user.id, "שורה\n\n")

    await DB.append_to_note_for_user(note.id, user.id, "עוד שורה")
    assert (await DB.get_note_by_id(note.id)).content == "שורה\nעוד שורה"


@pytest.mark.asyncio
async def test_appending_leaves_the_name_alone(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=986, username="t", first_name="T")
    note = await DB.create_note(user.id, "גוף", title="רופא משפחה")

    await DB.append_to_note_for_user(note.id, user.id, "עוד")
    stored = await DB.get_note_by_id(note.id)
    assert stored.title == "רופא משפחה"
    assert stored.content == "גוף\nעוד"


@pytest.mark.asyncio
async def test_another_user_cannot_append_to_a_note(db):
    DB = db.DatabaseManager
    owner = await DB.create_user(telegram_id=985, username="a", first_name="A")
    other = await DB.create_user(telegram_id=984, username="b", first_name="B")
    note = await DB.create_note(owner.id, "שלי")

    assert await DB.append_to_note_for_user(note.id, other.id, "נדחף") is False
    assert (await DB.get_note_by_id(note.id)).content == "שלי"


@pytest.mark.asyncio
async def test_appending_to_a_missing_note_reports_rather_than_raising(db):
    DB = db.DatabaseManager
    user = await DB.create_user(telegram_id=983, username="t", first_name="T")
    assert await DB.append_to_note_for_user(4242, user.id, "טקסט") is False
