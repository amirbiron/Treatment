"""Tests for the snooze choices and the inventory-tracking setting.

Two behaviours matter most here. A reminder already sitting in someone's chat
keeps its old buttons forever - Telegram never rewrites a delivered message - so
the old callback format has to keep working. And turning inventory tracking off
has to silence the proactive alerts, which are the loudest part of the feature.
"""

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

keyboards = importlib.import_module("utils.keyboards")


# --- snooze choices ----------------------------------------------------------


def test_the_reminder_offers_every_choice():
    markup = keyboards.get_reminder_keyboard(7)
    labels = [b.text for row in markup.inline_keyboard for b in row]

    for minutes in keyboards.SNOOZE_CHOICES:
        assert any(str(minutes) in label or "חצי שעה" in label for label in labels)


def test_the_choices_sit_on_one_row():
    """Three taps of equal weight, rather than a default with alternatives."""
    markup = keyboards.get_reminder_keyboard(7)
    snooze_rows = [
        row for row in markup.inline_keyboard
        if all("dose_snooze_" in b.callback_data for b in row)
    ]
    assert len(snooze_rows) == 1
    assert len(snooze_rows[0]) == len(keyboards.SNOOZE_CHOICES)


def test_half_an_hour_is_written_as_half_an_hour():
    assert "חצי שעה" in keyboards.format_snooze_label(30)
    assert "15" in keyboards.format_snooze_label(15)


def test_each_button_carries_its_own_minutes():
    markup = keyboards.get_reminder_keyboard(7)
    data = [
        b.callback_data for row in markup.inline_keyboard for b in row
        if b.callback_data.startswith("dose_snooze_")
    ]
    assert data == [f"dose_snooze_7_{m}" for m in keyboards.SNOOZE_CHOICES]


@pytest.mark.parametrize("minutes", keyboards.SNOOZE_CHOICES)
def test_a_choice_round_trips(minutes):
    medicine_id, parsed = keyboards.parse_snooze_callback(f"dose_snooze_42_{minutes}", 5)
    assert (medicine_id, parsed) == (42, minutes)


def test_an_old_reminder_still_snoozes():
    """Reminders delivered before this change carry the old two-part callback."""
    assert keyboards.parse_snooze_callback("dose_snooze_42", 5) == (42, 5)


def test_an_old_reminder_uses_the_users_configured_default():
    """Which is exactly what that button did before the choices existed."""
    assert keyboards.parse_snooze_callback("dose_snooze_42", 20) == (42, 20)


def test_an_unoffered_delay_falls_back_to_the_default():
    """A crafted callback must not schedule an arbitrary delay."""
    assert keyboards.parse_snooze_callback("dose_snooze_42_99999", 5) == (42, 5)


@pytest.mark.parametrize(
    "data", ["dose_snooze_abc", "dose_taken_42", "dose_snooze", "", "garbage"]
)
def test_something_that_is_not_a_snooze_is_rejected(data):
    medicine_id, _ = keyboards.parse_snooze_callback(data, 5)
    assert medicine_id is None


def test_a_non_numeric_choice_falls_back_rather_than_raising():
    assert keyboards.parse_snooze_callback("dose_snooze_42_soon", 5) == (42, 5)


# --- the inventory setting ---------------------------------------------------


def test_the_setting_defaults_to_on():
    """Nobody should lose a count they were relying on by upgrading."""
    from database import UserSettings

    assert UserSettings.__table__.c.track_inventory.default.arg is True


@pytest.mark.asyncio
async def test_a_mongo_document_written_before_the_setting_counts_as_on():
    """Those users were tracking inventory, so an absent key means on."""
    from database import DatabaseManagerMongo

    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={"user_id": 5, "snooze_minutes": 10})

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.user_settings = collection
        settings = await DatabaseManagerMongo.get_user_settings(5)

    assert settings.track_inventory is True


@pytest.mark.asyncio
async def test_a_mongo_document_that_turned_it_off_stays_off():
    from database import DatabaseManagerMongo

    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={"user_id": 5, "track_inventory": False})

    with patch("database._mongo_db") as mongo, patch("database._init_mongo", AsyncMock()):
        mongo.user_settings = collection
        settings = await DatabaseManagerMongo.get_user_settings(5)

    assert settings.track_inventory is False


def test_the_column_is_backfilled_for_existing_databases():
    """create_all does not alter a table that already exists, so upgrading an
    existing deployment needs the ALTER - without it every settings read fails."""
    source = open("database.py", encoding="utf-8").read()
    assert "ALTER TABLE user_settings ADD COLUMN track_inventory" in source
    assert "DEFAULT 1" in source, "existing users must keep tracking switched on"


@pytest.mark.asyncio
async def test_the_toggle_reaches_both_backends():
    """Signatures drift between the two implementations if nothing checks."""
    import inspect
    from database import DatabaseManager, DatabaseManagerMongo

    for manager in (DatabaseManager, DatabaseManagerMongo):
        params = inspect.signature(manager.update_user_settings).parameters
        assert "track_inventory" in params, f"{manager.__name__} cannot store the setting"


@pytest.mark.asyncio
async def test_reading_the_setting_defaults_to_showing_inventory_on_failure():
    """Hiding a count someone relies on is worse than showing a spare one."""
    import main as main_module

    with patch.object(
        main_module.DatabaseManager, "get_user_by_telegram_id",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        assert await main_module.tracks_inventory(1) is True


@pytest.mark.asyncio
async def test_an_unknown_user_still_sees_inventory():
    import main as main_module

    with patch.object(
        main_module.DatabaseManager, "get_user_by_telegram_id", AsyncMock(return_value=None)
    ):
        assert await main_module.tracks_inventory(1) is True


@pytest.mark.asyncio
async def test_the_setting_is_honoured_when_it_reads_cleanly():
    import main as main_module

    user = MagicMock(id=3)
    settings = MagicMock(track_inventory=False)
    with patch.object(
        main_module.DatabaseManager, "get_user_by_telegram_id", AsyncMock(return_value=user)
    ), patch.object(
        main_module.DatabaseManager, "get_user_settings", AsyncMock(return_value=settings)
    ):
        assert await main_module.tracks_inventory(1) is False


@pytest.mark.asyncio
async def test_a_reminder_drops_the_stock_line_when_tracking_is_off():
    """This is the message the complaint was about: מלאי: 0 on every reminder."""
    text = await _send_reminder_with(track_inventory=False)

    assert "מלאי נותר" not in text
    assert "מלאי נמוך" not in text
    assert "זמן לקחת תרופה" in text, "the reminder itself must still arrive"


@pytest.mark.asyncio
async def test_a_reminder_keeps_the_stock_line_when_tracking_is_on():
    text = await _send_reminder_with(track_inventory=True)

    assert "מלאי נותר" in text
    assert "מלאי נמוך" in text, "the low-stock warning belongs to whoever wants it"


async def _send_reminder_with(track_inventory: bool) -> str:
    """Drive one reminder through the scheduler and return the text sent."""
    import scheduler as scheduler_module

    medicine = MagicMock(id=1, name="דוגמה", dosage="1", is_active=True)
    medicine.inventory_count = 0
    medicine.low_stock_threshold = 5
    user = MagicMock(id=3, telegram_id=99, is_active=True)

    sched = scheduler_module.MedicineScheduler()
    sched.bot = MagicMock()
    sched.bot.send_message = AsyncMock()

    with patch.object(
        scheduler_module.DatabaseManager, "get_medicine_by_id", AsyncMock(return_value=medicine)
    ), patch.object(
        scheduler_module.DatabaseManager, "get_user_by_id", AsyncMock(return_value=user)
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(track_inventory=track_inventory)),
    ):
        await sched._send_medicine_reminder(3, 1)

    return sched.bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_turning_it_off_silences_the_unsolicited_alert():
    """The proactive 'you are low' message is the loudest part of the feature."""
    import scheduler as scheduler_module

    medicine = MagicMock(user_id=3)
    sched = scheduler_module.MedicineScheduler()

    with patch.object(
        scheduler_module.DatabaseManager,
        "get_low_stock_medicines",
        AsyncMock(return_value=[medicine]),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(track_inventory=False)),
    ), patch.object(
        sched, "_send_low_stock_alert", AsyncMock(), create=True
    ) as alert:
        await sched._check_low_inventory()

    alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_alert_still_goes_out_for_everyone_else():
    import scheduler as scheduler_module

    medicine = MagicMock(user_id=3)
    sched = scheduler_module.MedicineScheduler()

    with patch.object(
        scheduler_module.DatabaseManager,
        "get_low_stock_medicines",
        AsyncMock(return_value=[medicine]),
    ), patch.object(
        scheduler_module.DatabaseManager,
        "get_user_settings",
        AsyncMock(return_value=MagicMock(track_inventory=True)),
    ), patch.object(
        sched, "_send_low_stock_alert", AsyncMock(), create=True
    ) as alert:
        await sched._check_low_inventory()

    alert.assert_awaited_once()


def test_the_menu_button_stays_for_everyone():
    """It is built in thirty-five places; a conditional one would flicker."""
    labels = [
        button.text
        for row in keyboards.get_main_menu_keyboard().keyboard
        for button in row
    ]
    assert any("מלאי" in label and "בית מרקחת" not in label for label in labels)


@pytest.mark.asyncio
async def test_pressing_it_while_off_explains_itself_and_offers_the_way_back():
    import main as main_module

    message = MagicMock()
    message.reply_text = AsyncMock()

    await main_module.reply_inventory_is_off(message)

    text = message.reply_text.await_args.args[0]
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert "מעקב מלאי כבוי" in text
    assert markup.inline_keyboard[0][0].callback_data == "settings_inventory_toggle"


def test_the_explanation_lives_in_one_place():
    """It is reached from two menu paths; two copies would drift."""
    import main as main_module

    source = open("main.py", encoding="utf-8").read()
    assert source.count(main_module.INVENTORY_OFF_MESSAGE.split("\n")[0]) == 1


def test_the_low_stock_alert_sender_does_not_exist():
    """Recorded, not fixed.

    _check_low_inventory calls self._send_low_stock_alert, which is defined
    nowhere. The call raises AttributeError into the job's broad except, which
    logs "Failed to check inventory" - so these alerts have never once been
    sent. Writing the sender would be adding a feature, and the request here was
    for less inventory noise, not more. This test is here so the fact stops
    being invisible; delete it in the change that implements the sender.
    """
    import scheduler as scheduler_module

    assert not hasattr(scheduler_module.MedicineScheduler, "_send_low_stock_alert")
