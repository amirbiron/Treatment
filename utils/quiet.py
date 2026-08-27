"""Whether a user has muted the bot's reminders.

The scheduler and the menu both need this answer, and they must agree: a button
that says "מושתק" while reminders keep arriving is worse than no button. So the
flag is read here once, and the button label and the status line are built here
too - a screen cannot describe a state the sender does not honour.

The setting behind this is `silent_mode`, which the settings screen has offered
for a long time while nothing read it. Muting means the reminder is *not sent*
at all - it is not queued, not summarised later, and no missed-dose alert goes
to the caregivers for it. Someone asleep is not going to take a dose, and a
message waiting in the morning would only be noise.

Every failure path here answers "not muted". A reminder that arrives when it was
not wanted is an annoyance; one that never arrives because a settings read
failed is a missed dose.
"""

import logging

logger = logging.getLogger(__name__)


def reminders_muted(settings) -> bool:
    """Read the flag off a settings object, defaulting to not muted."""
    return bool(getattr(settings, "silent_mode", False))


async def reminders_muted_for_user(db_user) -> bool:
    """Look the setting up for a resolved user row."""
    from database import DatabaseManager

    if not db_user:
        return False
    try:
        return reminders_muted(await DatabaseManager.get_user_settings(db_user.id))
    except Exception:
        logger.exception("Could not read the mute setting; sending the reminder")
        return False


async def reminders_muted_for_db_id(user_id) -> bool:
    """Look the setting up when only the database id is at hand.

    The scheduler's jobs carry ids, not rows, and `get_user_settings` only needs
    the id - so this avoids a user lookup on every single reminder.
    """
    from types import SimpleNamespace

    return await reminders_muted_for_user(SimpleNamespace(id=user_id))


async def reminders_muted_for_telegram_id(telegram_user_id) -> bool:
    """Look the setting up from a Telegram id."""
    from database import DatabaseManager

    try:
        return await reminders_muted_for_user(
            await DatabaseManager.get_user_by_telegram_id(telegram_user_id)
        )
    except Exception:
        logger.exception("Could not resolve the user; sending the reminder")
        return False


def mute_button_label(muted: bool) -> str:
    """The button says what pressing it will do, not what the state is.

    "התראות: מופעלות" leaves the user guessing whether tapping turns them off or
    confirms them. An imperative does not.
    """
    return "🔔 הפעל התראות" if muted else "🔕 השתק התראות"


def mute_status_line(muted: bool) -> str:
    """The state itself, spelled out wherever the button appears."""
    if muted:
        return "🔕 ההתראות מושתקות - לא יישלחו תזכורות עד שתפעילו אותן"
    return "🔔 ההתראות פעילות"
