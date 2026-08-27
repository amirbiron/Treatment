"""Tests for muting reminders.

The setting behind the button (`silent_mode`) has existed for a long time while
nothing read it, so the thing worth pinning here is not that the flag is stored -
it is that every path which pushes a message on the bot's own initiative honours
it, and that the paths which deliberately ignore it keep ignoring it.

Muting means dropped, not deferred: nothing is queued for the morning, no
attempt is spent, and no caregiver is told about a dose the user was never asked
about.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

keyboards = importlib.import_module("utils.keyboards")
quiet = importlib.import_module("utils.quiet")


# --- reading the setting -----------------------------------------------------


def test_a_settings_object_without_the_field_is_not_muted():
    """A missing flag must not silence a bot someone depends on."""
    assert quiet.reminders_muted(MagicMock(spec=[])) is False


def test_the_flag_is_honoured_when_it_is_there():
    assert quiet.reminders_muted(MagicMock(silent_mode=True)) is True
    assert quiet.reminders_muted(MagicMock(silent_mode=False)) is False


@pytest.mark.asyncio
async def test_a_failed_settings_read_still_delivers():
    """An unwanted reminder is an annoyance. A missing one is a missed dose."""
    with patch(
        "database.DatabaseManager.get_user_settings",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        assert await quiet.reminders_muted_for_user(MagicMock(id=3)) is False


@pytest.mark.asyncio
async def test_an_unknown_user_is_not_muted():
    assert await quiet.reminders_muted_for_user(None) is False


@pytest.mark.asyncio
async def test_the_db_id_lookup_needs_no_user_row():
    """Jobs carry ids, not rows, so this must not cost a user lookup."""
    settings = AsyncMock(return_value=MagicMock(silent_mode=True))
    with patch("database.DatabaseManager.get_user_settings", settings), patch(
        "database.DatabaseManager.get_user_by_id", AsyncMock(side_effect=AssertionError)
    ):
        assert await quiet.reminders_muted_for_db_id(7) is True
    assert settings.await_args.args == (7,)


# --- the button --------------------------------------------------------------


def test_the_button_says_what_pressing_it_does():
    """A state label leaves the user guessing which way the tap goes."""
    assert "הפעל" in quiet.mute_button_label(muted=True)
    assert "השתק" in quiet.mute_button_label(muted=False)


def test_the_status_line_spells_out_the_consequence():
    """"מצב שקט: מופעל" does not tell anyone that no reminders will arrive."""
    assert "לא יישלחו תזכורות" in quiet.mute_status_line(muted=True)
    assert "לא יישלחו" not in quiet.mute_status_line(muted=False)


def test_the_toggle_keeps_its_old_callback():
    """Settings screens already sitting in a chat keep their working button."""
    assert keyboards.mute_toggle_button(False).callback_data == "rsilent_toggle"


def test_the_settings_screen_offers_the_toggle():
    markup = keyboards.get_reminders_settings_keyboard(5, 3, silent=True)
    labels = [b.text for row in markup.inline_keyboard for b in row]

    assert quiet.mute_button_label(muted=True) in labels


# --- what muting actually stops ----------------------------------------------


def _scheduler_with_bot():
    import scheduler as scheduler_module

    sched = scheduler_module.MedicineScheduler()
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()
    return sched


@pytest.mark.asyncio
@pytest.mark.parametrize("muted,sent", [(True, False), (False, True)])
async def test_muting_stops_the_medicine_reminder(muted, sent):
    import scheduler as scheduler_module

    sched = _scheduler_with_bot()
    medicine = MagicMock(id=1, name="דוגמה", dosage="1", is_active=True)
    medicine.inventory_count = 10
    medicine.low_stock_threshold = 5

    with patch.object(
        scheduler_module.DatabaseManager, "get_medicine_by_id", AsyncMock(return_value=medicine)
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_by_id",
        AsyncMock(return_value=MagicMock(id=3, telegram_id=99, is_active=True)),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=muted, track_inventory=True)),
    ):
        await sched._send_medicine_reminder(3, 1)

    assert sched.bot.send_message.await_count == (1 if sent else 0)


@pytest.mark.asyncio
async def test_a_muted_snooze_does_not_wake_a_caregiver():
    """The attempt cap is checked after the mute, not before.

    Otherwise a night of dropped reminders would spend every attempt and the
    last one would report a missed dose the user was never asked about.
    """
    import scheduler as scheduler_module
    from config import config

    sched = _scheduler_with_bot()
    sched.reminder_attempts["3_1"] = config.MAX_REMINDER_ATTEMPTS + 1

    with patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=True)),
    ), patch.object(
        sched, "_mark_dose_missed", AsyncMock(), create=True
    ) as missed, patch.object(
        sched, "_notify_caregivers_missed_dose", AsyncMock(), create=True
    ) as notified:
        await sched._send_snoozed_reminder(3, 1)

    missed.assert_not_awaited()
    notified.assert_not_awaited()
    sched.bot.send_message.assert_not_awaited()
    assert sched.reminder_attempts["3_1"] == config.MAX_REMINDER_ATTEMPTS + 1, (
        "a dropped reminder must not spend an attempt"
    )


@pytest.mark.asyncio
async def test_muting_stops_a_free_form_reminder_but_still_retires_it():
    """Its DateTrigger has fired and will not fire again. Leaving it active
    would strand it in the user's list, pending forever."""
    import scheduler as scheduler_module

    sched = _scheduler_with_bot()
    reminder = MagicMock(id=8, text="לשתות מים", repeat="once", is_active=True)

    with patch.object(
        scheduler_module.DatabaseManager,
        "get_custom_reminder_by_id",
        AsyncMock(return_value=reminder),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_by_id",
        AsyncMock(return_value=MagicMock(id=3, telegram_id=99, is_active=True)),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=True)),
    ), patch.object(
        scheduler_module.DatabaseManager, "set_custom_reminder_active", AsyncMock()
    ) as retire:
        await sched._send_custom_reminder(3, 8)

    sched.bot.send_message.assert_not_awaited()
    retire.assert_awaited_once_with(8, False)


@pytest.mark.asyncio
async def test_muting_stops_the_low_stock_alert():
    """It runs on an interval anchored to startup, so it lands at any hour."""
    import scheduler as scheduler_module

    sched = _scheduler_with_bot()

    with patch.object(
        scheduler_module.DatabaseManager,
        "get_low_stock_medicines",
        AsyncMock(return_value=[MagicMock(user_id=3)]),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=True, track_inventory=True)),
    ), patch.object(
        sched, "_send_low_stock_alert", AsyncMock(), create=True
    ) as alert:
        await sched._check_low_inventory()

    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_appointment_reminder_still_arrives_while_muted():
    """Deliberate: a doctor's appointment is one-shot and cannot be caught up.

    Muting is for the medicine schedule that repeats through the night, not for
    the reminder about next Tuesday's appointment.
    """
    import scheduler as scheduler_module
    from datetime import datetime

    sched = _scheduler_with_bot()
    appt = MagicMock(id=4, title="רופא משפחה", category="רופא", when_at=datetime(2026, 9, 1, 9, 0))

    # create=True: appointments are only implemented on the Mongo backend, and
    # which class DatabaseManager points at is decided by DB_BACKEND at import.
    with patch.object(
        scheduler_module.DatabaseManager,
        "get_upcoming_appointments",
        AsyncMock(return_value=[appt]),
        create=True,
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(silent_mode=True)),
    ):
        await sched._send_appointment_reminder(99, 4, 1)

    sched.bot.send_message.assert_awaited_once()


# --- storage -----------------------------------------------------------------


def test_both_backends_can_store_the_flag():
    """Signatures drift between the two implementations if nothing checks."""
    import inspect
    from database import DatabaseManager, DatabaseManagerMongo

    for manager in (DatabaseManager, DatabaseManagerMongo):
        params = inspect.signature(manager.update_user_settings).parameters
        assert "silent_mode" in params, f"{manager.__name__} cannot store the setting"


@pytest.mark.asyncio
async def test_a_mongo_document_written_before_the_flag_is_not_muted():
    from database import DatabaseManagerMongo

    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={"user_id": 5, "snooze_minutes": 10})

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.user_settings = collection
        settings = await DatabaseManagerMongo.get_user_settings(5)

    assert settings.silent_mode is False
